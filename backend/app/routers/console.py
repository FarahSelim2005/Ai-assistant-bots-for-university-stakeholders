"""The platform console (/console): the universities on the platform, for a platform owner.

POST /console/login                {email, password} -> {token, user}   (role platform_owner)
POST /console/logout
GET  /console/plans                [{key, name, monthly_token_cap, max_assistants}]
GET  /console/templates            the ready-made assistants
GET  /console/universities         [{id, slug, name, status, plan, hosts, assistants, users, tokens_month, ...}]
POST /console/universities         the "New university" wizard: name, subdomain, look, assistants, first admin
PUT  /console/universities/{id}    {status?: "active" | "suspended", plan?}

These routes work across universities, so they use the owner's connection (DB_ADMIN_USER, a
superuser: row-level security does not apply) and are only for platform owners, whose
accounts are made with python -m scripts.create_user --role platform_owner.
"""
import logging
import re
import time

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import auth, tenants
from app.auth import Session, platform_owner
from app.db import get_admin_connection
from app.routers.admin import COLOUR, LOGO, MAX_LOGO_CHARS, LoginRequest

router = APIRouter(prefix="/console")
log = logging.getLogger("uvicorn.error")

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
DEFAULT_AUDIENCES = '[{"key": "student", "title": "Student", "text": ""}, {"key": "staff", "title": "Staff", "text": ""}]'


class AdminIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str = Field(default="", max_length=120)
    password: str = Field(min_length=1, max_length=200)


class UniversityIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    short_name: str = Field(min_length=1, max_length=30)
    slug: str = Field(min_length=1, max_length=40)                    # the subdomain: <slug>.localhost
    host: str | None = Field(default=None, max_length=200)           # its own address (default <slug>.localhost)
    brand_primary: str = "#1f4e79"
    brand_accent: str = "#e8a317"
    brand_dark: str = "#1a1a1a"
    logo_url: str | None = Field(default=None, max_length=MAX_LOGO_CHARS)
    plan: str = "free"
    templates: list[str] = Field(default_factory=list, max_length=20)  # ready-made assistants to start with
    admin: AdminIn


class UniversityChange(BaseModel):
    status: str | None = None
    plan: str | None = None


# ---------------------------------------------------------------- login

@router.post("/login")
async def login(body: LoginRequest):
    result = await run_in_threadpool(auth.log_in, body.email, body.password, True)
    if result is None:
        await run_in_threadpool(time.sleep, 1)  # slows down password guessing
        raise HTTPException(401, "Wrong email or password.")
    token, session = result
    log.info("Console: %s logged in", session.email)
    return {"token": token, "user": {"email": session.email, "name": session.name, "role": session.role}}


@router.post("/logout")
def logout(authorization: str = Header(default="")):
    auth.log_out(authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


# ---------------------------------------------------------------- reading

@router.get("/plans", dependencies=[Depends(platform_owner)])
def list_plans():
    with get_admin_connection() as conn:
        rows = conn.execute("SELECT key, name, monthly_token_cap, max_assistants FROM plans ORDER BY position").fetchall()
    return [{"key": k, "name": n, "monthly_token_cap": cap, "max_assistants": most} for k, n, cap, most in rows]


@router.get("/templates", dependencies=[Depends(platform_owner)])
def list_templates():
    with get_admin_connection() as conn:
        rows = conn.execute("SELECT key, name, summary, audiences, skills FROM agent_templates ORDER BY position").fetchall()
    return [{"key": k, "name": n, "summary": s, "audiences": a, "skills": [x for x in sk if x not in ("cv", "map")]}
            for k, n, s, a, sk in rows]


@router.get("/universities", dependencies=[Depends(platform_owner)])
def list_universities():
    """Every university with its plan, addresses, assistants, users, chats and token use."""
    with get_admin_connection() as conn:
        rows = conn.execute("""
            SELECT t.id, t.slug, t.name, t.short_name, t.status, t.plan, p.name, p.monthly_token_cap, p.max_assistants,
                   t.brand_primary, t.created_at,
                   (SELECT array_agg(d.host ORDER BY d.is_primary DESC, d.host) FROM tenant_domains d WHERE d.tenant_id = t.id),
                   (SELECT count(*) FROM agents a WHERE a.tenant_id = t.id AND a.deleted_at IS NULL),
                   (SELECT coalesce(json_agg(json_build_object('email', u.email, 'role', u.role, 'active', u.active)
                                             ORDER BY u.role, u.email), '[]') FROM users u WHERE u.tenant_id = t.id),
                   (SELECT count(*) FROM conversations c WHERE c.tenant_id = t.id),
                   (SELECT coalesce(sum(x.total_tokens), 0) FROM usage x
                    WHERE x.tenant_id = t.id AND x.created_at >= date_trunc('month', now())),
                   (SELECT coalesce(sum(x.total_tokens), 0) FROM usage x WHERE x.tenant_id = t.id)
            FROM tenants t JOIN plans p ON p.key = t.plan ORDER BY t.created_at, t.slug""").fetchall()
    return [{"id": str(r[0]), "slug": r[1], "name": r[2], "short_name": r[3] or r[2], "status": r[4], "plan": r[5],
             "plan_name": r[6], "monthly_token_cap": r[7], "max_assistants": r[8], "colour": r[9],
             "created_at": r[10].isoformat(), "hosts": r[11] or [], "assistants": r[12], "users": r[13],
             "conversations": r[14], "tokens_month": int(r[15]), "tokens_total": int(r[16])} for r in rows]


# ---------------------------------------------------------------- changing

@router.post("/universities", dependencies=[Depends(platform_owner)])
def create_university(body: UniversityIn):
    """The "New university" wizard, in one transaction: the university (name, look, plan), its
    address, its assistants from the chosen templates (each in its own folder, named after the
    template) and its first admin. Nothing is made if any part is refused."""
    slug = body.slug.strip().lower()
    host = (body.host or f"{slug}.localhost").strip().lower()
    email = body.admin.email.strip().lower()
    if not SLUG.match(slug):
        raise HTTPException(400, "The subdomain may only have lower case letters, digits and -, up to 40.")
    if not HOST.match(host):
        raise HTTPException(400, "That is not a host name (for example demo.localhost or chat.uni.edu).")
    for key in ("brand_primary", "brand_accent", "brand_dark"):
        if not COLOUR.match(getattr(body, key)):
            raise HTTPException(400, "Colours are written like #c4161c.")
    if body.logo_url and not LOGO.match(body.logo_url):
        raise HTTPException(400, "The logo must be a PNG, JPEG, WebP or SVG picture.")
    problem = auth.password_problem(body.admin.password)
    if problem:
        raise HTTPException(400, f"Admin password: {problem}")
    if not re.match(r"^[^@\s]+@[^@\s]+$", email):
        raise HTTPException(400, "The admin's email is not an email address.")
    templates = list(dict.fromkeys(body.templates))
    with get_admin_connection() as conn:
        plan = conn.execute("SELECT max_assistants FROM plans WHERE key = %s", (body.plan,)).fetchone()
        if plan is None:
            raise HTTPException(400, f"Unknown plan '{body.plan}'.")
        if plan[0] is not None and len(templates) > plan[0]:
            raise HTTPException(400, f"The {body.plan} plan allows {plan[0]} assistants.")
        known = {k for (k,) in conn.execute("SELECT key FROM agent_templates WHERE key = ANY(%s)", (templates,))}
        if set(templates) - known:
            raise HTTPException(400, f"Unknown assistants: {', '.join(sorted(set(templates) - known))}.")
        if conn.execute("SELECT 1 FROM tenants WHERE slug = %s", (slug,)).fetchone():
            raise HTTPException(409, f"The subdomain '{slug}' is taken.")
        if conn.execute("SELECT 1 FROM tenant_domains WHERE host = %s", (host,)).fetchone():
            raise HTTPException(409, f"The address {host} is taken.")
        if conn.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone():
            raise HTTPException(409, "This email address already has an account.")
        tenant_id = conn.execute(
            "INSERT INTO tenants (slug, name, short_name, plan, brand_primary, brand_accent, brand_dark, logo_url, audiences) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (slug, body.name.strip(), body.short_name.strip(), body.plan, body.brand_primary, body.brand_accent,
             body.brand_dark, body.logo_url or None, DEFAULT_AUDIENCES)).fetchone()[0]
        conn.execute("INSERT INTO tenant_domains (host, tenant_id, is_primary) VALUES (%s, %s, true)", (host, tenant_id))
        # Its assistants: the templates' settings; no CV rewrites or campus map (it has neither yet).
        conn.execute("""
            INSERT INTO agents (tenant_id, template_key, name, summary, subtitle, description, audiences, answer_mode,
                                prompt_mode, instructions, fallback_en, fallback_ar, welcome, placeholder, examples,
                                skills, max_answer_tokens, position, folder)
            SELECT %s, key, name, summary, subtitle, description, audiences, answer_mode, prompt_mode, instructions,
                   fallback_en, fallback_ar, welcome, placeholder, examples, array_remove(array_remove(skills, 'cv'), 'map'),
                   max_answer_tokens, row_number() OVER (ORDER BY position), key
            FROM agent_templates WHERE key = ANY(%s)""", (tenant_id, templates))
        conn.execute("INSERT INTO users (tenant_id, email, name, role, password_hash) VALUES (%s, %s, %s, 'tenant_admin', %s)",
                     (tenant_id, email, body.admin.name, auth.hash_password(body.admin.password)))
    tenants._by_host.clear()
    log.info("Console: new university %s (%s) with %d assistants", body.name, host, len(templates))
    return {"id": str(tenant_id), "slug": slug, "host": host, "url": f"http://{host}:5173",
            "admin_url": f"http://{host}:5173/admin"}


@router.put("/universities/{tenant_id}")
def change_university(tenant_id: str, body: UniversityChange, session: Session = Depends(platform_owner)):
    """Suspend or reactivate a university (a suspended one answers 403 everywhere), or change its plan."""
    values = body.model_dump(exclude_unset=True)
    if "status" in values and values["status"] not in ("active", "suspended"):
        raise HTTPException(400, "The status must be active or suspended.")
    if not values:
        return {"ok": True}
    try:
        with get_admin_connection() as conn:
            changed = conn.execute(f"UPDATE tenants SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s",
                                   (*values.values(), tenant_id)).rowcount
    except (psycopg.errors.ForeignKeyViolation, psycopg.errors.InvalidTextRepresentation):
        raise HTTPException(400, "Unknown plan or university.")
    if not changed:
        raise HTTPException(404, "University not found.")
    tenants._by_host.clear()  # the next request sees the new status
    log.info("Console: %s changed university %s (%s)", session.email, tenant_id, values)
    return {"ok": True}
