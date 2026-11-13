"""The platform console (/console): the universities on the platform, for a platform owner.

POST /console/login                {email, password} -> {token, user}   (role platform_owner)
POST /console/logout
GET  /console/plans                [{key, name, price_egp, trial_days, monthly_token_cap, max_assistants, public, ...}]
GET  /console/templates            the ready-made assistants
GET  /console/universities         [{id, slug, name, status, plan, hosts, assistants, users, questions_30d,
                                     tokens_30d, cost_30d, tokens_month, ...}]
GET  /console/models               the platform's models (names only) and which API keys are set
GET  /console/usage                tokens, cost and questions per university and month (last 6 months)
POST /console/universities         "Add by hand" (the wizard): name, subdomain, look, assistants (their own,
                                   or ready-made ones), first admin
PUT  /console/universities/{id}    {status?: "active" | "suspended", plan?}   ("active" also approves a sign-up)
DELETE /console/universities/{id} {confirm: "<subdomain>"}: delete it for good (a pg_dump backup first)
PUT  /console/plans/{key}          {name?, price_egp?, monthly_token_cap?, max_assistants?, trial_days?, public?, description?}
GET  /console/settings             {require_review, payment_provider}
PUT  /console/settings             {require_review}: new sign-ups wait for approval
GET  /console/subscriptions        the signed-up universities' subscriptions and the latest billing events
POST /console/subscriptions/{id}/simulate-month   {payment: "succeeds" | "fails"}   (test mode)
POST /console/subscriptions/{id}/extend-trial     {days}

These routes work across universities, so they use the owner's connection (DB_ADMIN_USER, a
superuser: row-level security does not apply) and are only for platform owners, whose
accounts are made with python -m scripts.create_user --role platform_owner.
"""
import logging
import shutil
import time
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import agents, auth, backup, config, tenants, universities
from app.auth import Session, platform_owner
from app.billing import service
from app.db import get_admin_connection
from app.routers.admin import MAX_LOGO_CHARS, LoginRequest

router = APIRouter(prefix="/console")
log = logging.getLogger("uvicorn.error")

class AdminIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str = Field(default="", max_length=120)
    password: str = Field(min_length=1, max_length=200)


class AssistantIn(BaseModel):
    """An assistant made by the wizard: its own name and what it handles, optionally starting
    from a ready-made template (whose instructions, texts and skills it then gets)."""
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=600)
    template_key: str | None = Field(default=None, max_length=40)


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
    assistants: list[AssistantIn] = Field(default_factory=list, max_length=50)
    templates: list[str] = Field(default_factory=list, max_length=20)  # ready-made ones by key (as they are)
    admin: AdminIn


class UniversityChange(BaseModel):
    status: str | None = None
    plan: str | None = None


class PlanIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    price_egp: int | None = Field(default=None, ge=0, le=10_000_000)
    monthly_token_cap: int | None = Field(default=None, gt=0)
    max_assistants: int | None = Field(default=None, gt=0, le=1000)
    trial_days: int | None = Field(default=None, gt=0, le=365)
    public: bool | None = None
    description: str | None = Field(default=None, max_length=300)


class SettingsIn(BaseModel):
    require_review: bool


class SimulateIn(BaseModel):
    payment: Literal["succeeds", "fails"]


class DeleteIn(BaseModel):
    confirm: str = Field(min_length=1, max_length=40)  # the university's subdomain, typed again


class ExtendIn(BaseModel):
    days: int = Field(gt=0, le=90)


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
    """Every plan with its price (EGP a month), caps, trial days and whether the public sign-up offers it."""
    with get_admin_connection() as conn:
        return service.plans(conn)


@router.get("/templates", dependencies=[Depends(platform_owner)])
def list_templates():
    with get_admin_connection() as conn:
        rows = conn.execute("SELECT key, name, summary, audiences, skills FROM agent_templates ORDER BY position").fetchall()
    return [{"key": k, "name": n, "summary": s, "audiences": a, "skills": [x for x in sk if x != "map"]}
            for k, n, s, a, sk in rows]


@router.get("/universities", dependencies=[Depends(platform_owner)])
def list_universities():
    """Every university with its plan, addresses, assistants, users, chats and token use."""
    with get_admin_connection() as conn:
        service.settle(conn)  # subscription statuses up to date
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
                   (SELECT coalesce(sum(x.total_tokens), 0) FROM usage x WHERE x.tenant_id = t.id),
                   (SELECT count(*) FROM messages m WHERE m.tenant_id = t.id AND m.role = 'user'
                    AND m.created_at >= now() - interval '30 days'),
                   (SELECT coalesce(sum(x.total_tokens), 0) FROM usage x
                    WHERE x.tenant_id = t.id AND x.created_at >= now() - interval '30 days'),
                   (SELECT coalesce(sum(x.cost_usd), 0) FROM usage x
                    WHERE x.tenant_id = t.id AND x.created_at >= now() - interval '30 days'),
                   t.signed_up_at, s.status, p.price_egp
            FROM tenants t JOIN plans p ON p.key = t.plan LEFT JOIN subscriptions s ON s.tenant_id = t.id
            ORDER BY t.created_at, t.slug""").fetchall()
    return [{"id": str(r[0]), "slug": r[1], "name": r[2], "short_name": r[3] or r[2], "status": r[4], "plan": r[5],
             "plan_name": r[6], "monthly_token_cap": r[7], "max_assistants": r[8], "colour": r[9],
             "created_at": r[10].isoformat(), "hosts": r[11] or [], "assistants": r[12], "users": r[13],
             "conversations": r[14], "tokens_month": int(r[15]), "tokens_total": int(r[16]),
             "questions_30d": r[17], "tokens_30d": int(r[18]), "cost_30d": float(r[19]),
             "signed_up_at": r[20].isoformat() if r[20] else None, "subscription": r[21], "price_egp": r[22]}
            for r in rows]


@router.get("/models", dependencies=[Depends(platform_owner)])
def list_models():
    """The platform's models from .env (names only; keys are never shown, only whether they are
    set) and how much each was used in the last 30 days, across all universities."""
    with get_admin_connection() as conn:
        rows = conn.execute("SELECT model, kind, count(*), sum(total_tokens), sum(cost_usd) FROM usage "
                            "WHERE created_at >= now() - interval '30 days' GROUP BY model, kind "
                            "ORDER BY sum(total_tokens) DESC").fetchall()
    roles = [("Answers", [config.LABS_MODEL, *config.LABS_BACKUP_MODELS]),
             ("Pictures", [config.VISION_MODEL, *config.VISION_BACKUP_MODELS]),
             ("CV rewrites", [config.CAREER_MODEL, *config.CAREER_BACKUP_MODELS]),
             ("Document editor", [config.DOC_EDIT_MODEL, *config.DOC_EDIT_BACKUP_MODELS]),
             ("Embeddings", [config.EMBEDDING_MODEL]),
             ("Local backup (Ollama)", [config.OLLAMA_MODEL])]
    return {"roles": [{"role": role, "models": [m for m in models if m]} for role, models in roles],
            "keys": {"OpenRouter": bool(config.OPENROUTER_API_KEY), "Groq": bool(config.GROQ_API_KEY)},
            "usage_30d": [{"model": m, "kind": k, "calls": n, "tokens": int(t or 0), "cost": float(c or 0)}
                          for m, k, n, t, c in rows]}


@router.get("/usage", dependencies=[Depends(platform_owner)])
def usage_by_month():
    """Tokens, cost and model calls per university and month (the last 6 months)."""
    with get_admin_connection() as conn:
        rows = conn.execute("""
            SELECT t.name, to_char(date_trunc('month', x.created_at), 'YYYY-MM'), count(*),
                   sum(x.total_tokens), sum(x.cost_usd)
            FROM usage x JOIN tenants t ON t.id = x.tenant_id
            WHERE x.created_at >= date_trunc('month', now()) - interval '5 months'
            GROUP BY 1, 2 ORDER BY 2 DESC, 4 DESC""").fetchall()
    return [{"university": u, "month": month, "calls": n, "tokens": int(t or 0), "cost": float(c or 0)}
            for u, month, n, t, c in rows]


# ---------------------------------------------------------------- changing

@router.post("/universities", dependencies=[Depends(platform_owner)])
def create_university(body: UniversityIn):
    """"Add by hand" (the wizard), in one transaction: the university, its address, its
    assistants and its first admin (app/universities.py). Nothing is made if any part is
    refused. A university added by hand has no subscription: billing never pauses it."""
    problem = auth.password_problem(body.admin.password)
    if problem:
        raise HTTPException(400, f"Admin password: {problem}")
    assistants = [*(a.model_dump() for a in body.assistants),
                  *({"name": key, "template_key": key} for key in dict.fromkeys(body.templates))]
    with get_admin_connection() as conn:
        tenant_id, host = universities.create(
            conn, name=body.name, short_name=body.short_name, slug=body.slug, host=body.host, plan=body.plan,
            assistants=assistants, admin_email=body.admin.email, admin_name=body.admin.name,
            password_hash=auth.hash_password(body.admin.password), brand_primary=body.brand_primary,
            brand_accent=body.brand_accent, brand_dark=body.brand_dark, logo_url=body.logo_url)
    tenants._by_host.clear()
    log.info("Console: new university %s (%s) with %d assistants", body.name, host, len(assistants))
    return {"id": str(tenant_id), "slug": body.slug.strip().lower(), "host": host, "url": f"http://{host}:5173",
            "admin_url": f"http://{host}:5173/admin"}


@router.put("/universities/{tenant_id}")
def change_university(tenant_id: str, body: UniversityChange, session: Session = Depends(platform_owner)):
    """Suspend or reactivate a university (a suspended one answers 403 everywhere), approve a sign-up
    waiting for review ("active"), or change its plan (and its subscription's)."""
    values = body.model_dump(exclude_unset=True)
    if "status" in values and values["status"] not in ("active", "suspended"):
        raise HTTPException(400, "The status must be active or suspended.")
    if not values:
        return {"ok": True}
    try:
        with get_admin_connection() as conn:
            changed = conn.execute(f"UPDATE tenants SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s",
                                   (*values.values(), tenant_id)).rowcount
            if "plan" in values:
                conn.execute("UPDATE subscriptions SET plan_key = %s, updated_at = now() WHERE tenant_id = %s",
                             (values["plan"], tenant_id))
    except (psycopg.errors.ForeignKeyViolation, psycopg.errors.InvalidTextRepresentation):
        raise HTTPException(400, "Unknown plan or university.")
    if not changed:
        raise HTTPException(404, "University not found.")
    tenants._by_host.clear()  # the next request sees the new status
    log.info("Console: %s changed university %s (%s)", session.email, tenant_id, values)
    return {"ok": True}


@router.delete("/universities/{tenant_id}")
def delete_university(tenant_id: str, body: DeleteIn, session: Session = Depends(platform_owner)):
    """Delete a university for good: its assistants, documents (files too), chats, ratings,
    users, usage, sign-ups and payments. A full pg_dump backup is made first; without it
    nothing is deleted. The subdomain must be typed again ("confirm"). GIU's documents in
    data/raw/ (kept in git) are left on disk."""
    with get_admin_connection() as conn:
        row = conn.execute("SELECT slug, name FROM tenants WHERE id = %s", (tenant_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "University not found.")
    slug, name = row
    if body.confirm.strip().lower() != slug:
        raise HTTPException(400, f"Type {slug} to confirm.")
    try:
        saved = backup.backup(f"deleting-{slug}")
    except backup.BackupFailed as error:
        raise HTTPException(500, str(error))
    with get_admin_connection() as conn:
        removed = universities.delete(conn, tenant_id)
    folder = tenants.data_dir(tenants.Tenant(tenant_id, slug, name))
    if folder.resolve().is_relative_to(config.TENANTS_DATA_DIR.resolve()) and folder.exists():
        shutil.rmtree(folder)  # only data/tenants/<slug>/, never data/raw/
    tenants._by_host.clear()
    agents._cache.pop(tenant_id, None)
    for token, other in list(auth._sessions.items()):  # its users are logged out
        if str(other.tenant_id) == str(tenant_id):
            auth._sessions.pop(token, None)
    log.warning("Console: %s DELETED university %s (%s); backup %s; rows %s", session.email, name, slug, saved.name, removed)
    return {"ok": True, "backup": str(saved), "removed": removed}


# ---------------------------------------------------------------- plans, sign-ups and subscriptions

@router.put("/plans/{key}")
def change_plan(key: str, body: PlanIn, session: Session = Depends(platform_owner)):
    """Change a plan's name, price (EGP a month), caps, trial days, description or whether the
    public sign-up offers it. null caps mean "no limit". A new price applies from the next payment."""
    values = body.model_dump(exclude_unset=True)
    if any(key_ in values and values[key_] is None for key_ in ("name", "price_egp", "public", "description")):
        raise HTTPException(400, "Name, price, description and public cannot be empty.")
    if not values:
        return {"ok": True}
    with get_admin_connection() as conn:
        current = service.plan(conn, key)
        if current is None:
            raise HTTPException(404, "Unknown plan.")
        if {**current, **values}["trial_days"] and {**current, **values}["price_egp"] > 0:
            raise HTTPException(400, "A trial plan must be free (price 0).")
        conn.execute(f"UPDATE plans SET {', '.join(f'{k} = %s' for k in values)} WHERE key = %s", (*values.values(), key))
    log.info("Console: %s changed plan %s (%s)", session.email, key, values)
    return {"ok": True}


@router.get("/settings", dependencies=[Depends(platform_owner)])
def get_settings():
    with get_admin_connection() as conn:
        return {"require_review": service.require_review(conn), "payment_provider": config.PAYMENT_PROVIDER}


@router.put("/settings")
def change_settings(body: SettingsIn, session: Session = Depends(platform_owner)):
    """"Require review before going live": new sign-ups wait (status review) until approved here."""
    with get_admin_connection() as conn:
        conn.execute("UPDATE platform_settings SET value = %s WHERE key = 'require_review'",
                     ("true" if body.require_review else "false",))
    log.info("Console: %s set require_review = %s", session.email, body.require_review)
    return {"ok": True}


@router.get("/subscriptions", dependencies=[Depends(platform_owner)])
def list_subscriptions():
    """The universities that signed up themselves: plan, status, dates, payments; the latest events."""
    return service.all_subscriptions()


@router.post("/subscriptions/{tenant_id}/simulate-month")
def simulate_month(tenant_id: str, body: SimulateIn, session: Session = Depends(platform_owner)):
    """Test mode: a month passes and the renewal payment succeeds or fails."""
    result = service.simulate_month(tenant_id, body.payment == "succeeds")
    log.info("Console: %s simulated a month for %s (payment %s)", session.email, tenant_id, body.payment)
    return result


@router.post("/subscriptions/{tenant_id}/extend-trial")
def extend_trial(tenant_id: str, body: ExtendIn, session: Session = Depends(platform_owner)):
    service.extend_trial(tenant_id, body.days)
    log.info("Console: %s extended the trial of %s by %d days", session.email, tenant_id, body.days)
    return {"ok": True}
