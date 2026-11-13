"""University admin routes (/admin), for the university of the request's host.

Logins (app/auth.py): POST /admin/login {email, password} -> {token, user}; every other route
needs "Authorization: Bearer <token>". Roles: tenant_admin (everything below) and editor
(documents, and reading the assistants list).

POST   /admin/login                 {email, password} -> {token, user}
POST   /admin/login/ticket          {ticket} -> {token, user}   the one-time link after the public sign-up
POST   /admin/logout
GET    /admin/me                    {user, university}
POST   /admin/me/password           {current_password, new_password}   (any role)
GET    /admin/analytics             questions, chats, unanswered %, ratings (30 days), per assistant
GET    /admin/agents                [{id, folder, name, ..., live, active_skills}]   (editors too)
GET    /admin/agent-templates       ready-made assistants to start from
POST   /admin/agents                {template_key?, name?, ...} -> {id}
PUT    /admin/agents/{id}           {name?, audiences?, answer_mode?, skills?, instructions?, ..., live?}
DELETE /admin/agents/{id}           hidden everywhere; its chats and documents are kept
POST   /admin/agents/order          {ids: [...]}   the order on the start screen
GET    /admin/branding              name, short name, logo, colours, intro, audiences
PUT    /admin/branding              {name?, short_name?, logo_url?, brand_*?, intro?, audiences?}
GET    /admin/users                 this university's users
POST   /admin/users                 {email, name, role, password} -> {id}
PUT    /admin/users/{id}            {name?, role?, active?, password?}
GET    /admin/documents             [{id, agent, agent_name, folder, filename, updated_at}]   (editors too)
GET    /admin/documents/{id}        {id, agent, filename, content}
POST   /admin/documents             {agent, filename, content} -> {id, chunks}
PUT    /admin/documents/{id}        {agent, filename, content} -> {id, chunks}   (changing the agent moves it)
DELETE /admin/documents/{id}

Documents are in one folder per assistant, its readable `folder` (GIU data/raw/<folder>/,
other universities data/tenants/<slug>/<folder>/). `agent` in a document request is the
assistant's id (or the template key of one of GIU's: "labs_research"). Every document change
is re-indexed at once (chunks + embeddings), so the assistants answer from the new text
right away.
"""
import base64
import binascii
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import auth, config, tenants, usage
from app.agents import agents_of, find_agent, load_agent
from app.agents.templates import ANSWER_MODES, PROMPT_MODES, SKILLS, skills_for
from app.auth import Session, tenant_admin, university_user
from app.db import get_connection
from scripts.ingest import ingest_file

router = APIRouter(prefix="/admin")
log = logging.getLogger("uvicorn.error")

DOCUMENT_TYPES = (".md", ".txt")
AUDIENCE_KEY = re.compile(r"^[a-z0-9_]{1,30}$")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
LOGO = re.compile(r"^(data:image/(png|jpeg|webp|svg\+xml);base64,[A-Za-z0-9+/=]+|/[\w./-]+|https://\S+)$")
MAX_LOGO_CHARS = 400_000  # a data URL of about 300 KB


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class DocumentIn(BaseModel):
    agent: str = Field(min_length=1, max_length=64)
    filename: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=config.ADMIN_MAX_DOCUMENT_CHARS)


class AgentIn(BaseModel):
    """An assistant's settings. On create, missing fields come from the template (if given);
    on update, missing fields stay as they are."""
    template_key: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    summary: str | None = Field(default=None, max_length=200)
    subtitle: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=3000)
    audiences: list[str] | None = Field(default=None, min_length=1, max_length=10)
    answer_mode: str | None = None
    prompt_mode: str | None = None  # "composed" (built from parts) or "complete" (instructions = whole prompt)
    instructions: str | None = Field(default=None, max_length=20000)
    fallback_en: str | None = Field(default=None, max_length=500)
    fallback_ar: str | None = Field(default=None, max_length=500)
    welcome: str | None = Field(default=None, max_length=300)
    placeholder: str | None = Field(default=None, max_length=200)
    examples: list[str] | None = Field(default=None, max_length=6)
    skills: list[str] | None = Field(default=None, max_length=len(SKILLS))
    max_answer_tokens: int | None = Field(default=None, ge=50, le=4000)
    model: str | None = Field(default=None, max_length=120)
    backup_models: list[str] | None = Field(default=None, max_length=5)
    similarity_threshold: float | None = Field(default=None, ge=0, le=1)
    position: int | None = Field(default=None, ge=0, le=1000)
    live: bool | None = None


class OrderIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


class AudienceIn(BaseModel):
    key: str = Field(min_length=1, max_length=30)
    title: str = Field(min_length=1, max_length=40)
    text: str = Field(default="", max_length=160)


class BrandingIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    short_name: str | None = Field(default=None, min_length=1, max_length=30)
    logo_url: str | None = Field(default=None, max_length=MAX_LOGO_CHARS)  # "" removes the logo
    brand_primary: str | None = None
    brand_accent: str | None = None
    brand_dark: str | None = None
    intro: str | None = Field(default=None, max_length=600)
    audiences: list[AudienceIn] | None = Field(default=None, min_length=1, max_length=6)


class UserIn(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=200)
    name: str | None = Field(default=None, max_length=120)
    role: str | None = None
    password: str | None = Field(default=None, max_length=200)
    active: bool | None = None


# ---------------------------------------------------------------- login

@router.post("/login")
async def login(body: LoginRequest):
    result = await run_in_threadpool(auth.log_in, body.email, body.password)
    if result is None:
        await run_in_threadpool(time.sleep, 1)  # slows down password guessing
        raise HTTPException(401, "Wrong email or password.")
    token, session = result
    log.info("Admin: %s logged in (%s)", session.email, session.role)
    return {"token": token, "user": {"email": session.email, "name": session.name, "role": session.role}}


class TicketIn(BaseModel):
    ticket: str = Field(min_length=10, max_length=100)


@router.post("/login/ticket")
def login_with_ticket(body: TicketIn):
    """The one-time login link from the sign-up (auth.issue_ticket)."""
    result = auth.redeem_ticket(body.ticket)
    if result is None:
        raise HTTPException(401, "This login link has expired. Please log in with your email and password.")
    token, session = result
    return {"token": token, "user": {"email": session.email, "name": session.name, "role": session.role}}


@router.post("/logout")
def logout(authorization: str = Header(default="")):
    auth.log_out(authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


@router.get("/me")
def me(session: Session = Depends(university_user)):
    tenant = tenants.current()
    return {"user": {"email": session.email, "name": session.name, "role": session.role},
            "university": {"name": tenant.name, "short_name": tenant.short, "slug": tenant.slug}}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


@router.post("/me/password")
def change_my_password(body: PasswordChange, session: Session = Depends(university_user)):
    """Any user changes their own password (the current one is needed)."""
    problem = auth.password_problem(body.new_password)
    if problem:
        raise HTTPException(400, problem)
    tenant_id = tenants.current_id()
    with get_connection(tenant_id) as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = %s AND tenant_id = %s",
                           (session.user_id, tenant_id)).fetchone()
        if row is None or not auth.check_password(body.current_password, row[0]):
            raise HTTPException(400, "The current password is not right.")
        conn.execute("UPDATE users SET password_hash = %s WHERE id = %s AND tenant_id = %s",
                     (auth.hash_password(body.new_password), session.user_id, tenant_id))
    return {"ok": True}


@router.get("/analytics", dependencies=[Depends(university_user)])
def analytics():
    """The last 30 days: questions, chats (users do not sign in, so a chat stands for a user),
    unanswered questions (answered with an assistant's "no information" text), ratings; per
    assistant, and the latest unanswered questions."""
    tenant_id = tenants.current_id()
    agents = agents_of(tenant_id)
    fallbacks = sorted({text for a in agents for text in (a.fallback_message, a.fallback_message_ar) if text})
    with get_connection(tenant_id) as conn:
        rows = conn.execute("""
            SELECT c.agent_id, q.content, a.content, q.created_at, f.rating
            FROM messages q
            JOIN conversations c ON c.id = q.conversation_id AND c.tenant_id = q.tenant_id
            LEFT JOIN LATERAL (SELECT id, content FROM messages a WHERE a.conversation_id = q.conversation_id
                               AND a.tenant_id = q.tenant_id AND a.role = 'assistant' AND a.id > q.id
                               ORDER BY a.id LIMIT 1) a ON true
            LEFT JOIN LATERAL (SELECT avg(rating) AS rating FROM feedback f WHERE f.message_id = a.id
                               AND f.tenant_id = q.tenant_id) f ON true
            WHERE q.tenant_id = %s AND q.role = 'user' AND q.created_at >= now() - interval '30 days'
            ORDER BY q.id DESC""", (tenant_id,)).fetchall()
        chats = conn.execute("SELECT count(*) FROM conversations WHERE tenant_id = %s "
                             "AND created_at >= now() - interval '30 days'", (tenant_id,)).fetchone()[0]
    names = {a.id: a.display_name for a in agents}
    per = {}
    unanswered_list = []
    ratings = []
    for agent_id, question, answer, at, rating in rows:
        stats = per.setdefault(agent_id, {"questions": 0, "unanswered": 0, "ratings": []})
        stats["questions"] += 1
        if answer in fallbacks:
            stats["unanswered"] += 1
            if len(unanswered_list) < 15:
                unanswered_list.append({"question": question.split("\n[Attached")[0], "assistant": names.get(agent_id, "Deleted assistant"),
                                        "at": at.isoformat()})
        if rating is not None:
            stats["ratings"].append(float(rating))
            ratings.append(float(rating))
    unanswered = sum(s["unanswered"] for s in per.values())
    percent = lambda part, whole: round(100 * part / whole, 1) if whole else 0.0
    average = lambda values: round(sum(values) / len(values), 2) if values else None
    return {
        "questions_30d": len(rows), "chats_30d": chats, "unanswered_30d": unanswered,
        "unanswered_pct": percent(unanswered, len(rows)), "average_rating": average(ratings), "ratings": len(ratings),
        "per_assistant": [{"id": str(agent_id), "name": names.get(agent_id, "Deleted assistant"),
                           "questions": st["questions"], "unanswered_pct": percent(st["unanswered"], st["questions"]),
                           "average_rating": average(st["ratings"])}
                          for agent_id, st in sorted(per.items(), key=lambda item: -item[1]["questions"])],
        "recent_unanswered": unanswered_list,
    }


# ---------------------------------------------------------------- assistants

def agent_out(agent) -> dict:
    s = agent.settings
    return {"id": agent.name, "folder": s.folder, "template_key": s.template_key, "name": s.name,
            "summary": s.summary, "subtitle": s.subtitle, "description": s.description, "audiences": list(s.audiences),
            "answer_mode": s.answer_mode, "prompt_mode": s.prompt_mode, "instructions": s.instructions,
            "fallback_en": s.fallback_en,
            "fallback_ar": s.fallback_ar, "welcome": s.welcome, "placeholder": s.placeholder,
            "examples": list(s.examples), "skills": list(s.skills), "max_answer_tokens": s.max_answer_tokens,
            "model": s.model, "backup_models": list(s.backup_models), "similarity_threshold": s.similarity_threshold,
            "position": s.position, "live": s.live, "active_skills": agent.active_skills(),
            "documents": document_count(s.folder)}


def document_count(folder_name: str) -> int:
    folder = tenants.data_dir(tenants.current()) / folder_name
    return sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() in DOCUMENT_TYPES) if folder.is_dir() else 0


def audience_keys() -> list[str]:
    return [audience["key"] for audience in tenants.current().audiences]


def checked_settings(values: dict) -> dict:
    """The given settings, refused (400) when one is not allowed."""
    if values.get("audiences") is not None:
        unknown = set(values["audiences"]) - set(audience_keys())
        if unknown or not values["audiences"]:
            raise HTTPException(400, f"Audiences must be some of: {', '.join(audience_keys())}.")
    if values.get("answer_mode") is not None and values["answer_mode"] not in ANSWER_MODES:
        raise HTTPException(400, f"The answer mode must be one of: {', '.join(ANSWER_MODES)}.")
    if values.get("prompt_mode") is not None and values["prompt_mode"] not in PROMPT_MODES:
        raise HTTPException(400, f"The prompt mode must be one of: {', '.join(PROMPT_MODES)}.")
    skills = values.get("skills")
    if skills is not None:
        unknown = set(skills) - set(SKILLS)
        if unknown:
            raise HTTPException(400, f"Unknown skills: {', '.join(sorted(unknown))}. Choose from: {', '.join(SKILLS)}.")
    if values.get("name") is not None and not values["name"].strip():
        raise HTTPException(400, "The name must not be empty.")
    return values


@router.get("/agents", dependencies=[Depends(university_user)])
def list_agents():
    return [agent_out(agent) for agent in agents_of(tenants.current_id())]


@router.get("/agent-templates", dependencies=[Depends(tenant_admin)])
def list_templates():
    with get_connection(tenants.current_id()) as conn:
        rows = conn.execute("SELECT key, name, summary, description, audiences, answer_mode, skills "
                            "FROM agent_templates ORDER BY position, key").fetchall()
    return [{"key": k, "name": n, "summary": s, "description": d, "audiences": a, "answer_mode": m, "skills": sk}
            for k, n, s, d, a, m, sk in rows]


# The settings a template gives (agent_templates has no model, threshold, position or live).
TEMPLATE_FIELDS = ["name", "summary", "subtitle", "description", "audiences", "answer_mode", "prompt_mode",
                   "instructions", "fallback_en", "fallback_ar", "welcome", "placeholder", "examples", "skills",
                   "max_answer_tokens"]


@router.post("/agents", dependencies=[Depends(tenant_admin)])
def create_agent(body: AgentIn):
    """A new assistant: the template's settings (if one is given), changed by the fields sent.
    It goes last in the list unless a position is given. From a template, its audiences are
    the university's (all of them when none match). Skills, unless the request names them: a
    ready-made assistant's as at GIU (the campus map only where there is one), a new one's the
    usual ones (files, pictures, editor, voice); it answers from the documents uploaded for it."""
    tenant_id = tenants.current_id()
    with get_connection(tenant_id) as conn:
        settings = {}
        if body.template_key:
            row = conn.execute(f"SELECT {', '.join(TEMPLATE_FIELDS)} FROM agent_templates WHERE key = %s",
                               (body.template_key,)).fetchone()
            if row is None:
                raise HTTPException(400, f"Unknown template '{body.template_key}'.")
            settings = dict(zip(TEMPLATE_FIELDS, row))
            settings["audiences"] = [a for a in settings["audiences"] if a in audience_keys()] or audience_keys()
        else:
            settings["audiences"] = audience_keys()
        # A ready-made one: its GIU skills; from scratch: the usual ones (those sent with the request win)
        settings["skills"] = skills_for(tenants.current().campus_map, settings.get("skills"))
        settings.update({k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "template_key"})
        checked_settings(settings)
        if not settings.get("name"):
            raise HTTPException(400, "Give the assistant a name (or start from a template).")
        check_assistant_limit(conn, tenant_id)
        settings["folder"] = new_folder(settings["name"], body.template_key, conn, tenant_id)
        if "position" not in settings:
            settings["position"] = conn.execute("SELECT coalesce(max(position), 0) + 1 FROM agents WHERE tenant_id = %s",
                                                (tenant_id,)).fetchone()[0]
        columns = ["tenant_id", "template_key", *settings]
        agent_id = conn.execute(
            f"INSERT INTO agents ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id",
            (tenant_id, body.template_key, *settings.values())).fetchone()[0]
    log.info("Admin: new assistant %s (%s)", settings["name"], agent_id)
    return {"id": str(agent_id)}


def check_assistant_limit(conn, tenant_id) -> None:
    """403 when the university's plan allows no more assistants (deleted ones do not count)."""
    count, limit = conn.execute(
        "SELECT (SELECT count(*) FROM agents WHERE tenant_id = %s AND deleted_at IS NULL), "
        "       (SELECT p.max_assistants FROM tenants t JOIN plans p ON p.key = t.plan WHERE t.id = %s)",
        (tenant_id, tenant_id)).fetchone()
    if limit is not None and count >= limit:
        raise HTTPException(403, f"Your plan allows {limit} assistants. Delete one, or ask for a bigger plan.")


def new_folder(name: str, template_key: str | None, conn, tenant_id) -> str:
    """A readable folder name not used by another of the university's assistants (deleted ones
    too: their documents are kept): the template key, or one made from the name
    ("Library Helper" -> "library_helper"), with _2, _3 ... added when it is taken."""
    taken = {f for (f,) in conn.execute("SELECT folder FROM agents WHERE tenant_id = %s", (tenant_id,))}
    base = template_key or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "assistant"
    folder, number = base, 1
    while folder in taken:
        number += 1
        folder = f"{base}_{number}"
    return folder


def own_agent(agent_id: str):
    agent = load_agent(tenants.current_id(), agent_id)
    if agent is None:
        raise HTTPException(404, "Assistant not found.")
    return agent


@router.put("/agents/{agent_id}", dependencies=[Depends(tenant_admin)])
def update_agent(agent_id: str, body: AgentIn):
    """Change an assistant. New audiences also apply to its documents' chunks at once."""
    agent = own_agent(agent_id)
    values = checked_settings({k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "template_key"})
    if values:
        tenant_id = tenants.current_id()
        with get_connection(tenant_id) as conn:
            conn.execute(f"UPDATE agents SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s AND tenant_id = %s",
                         (*values.values(), agent.id, tenant_id))
            if "audiences" in values:
                conn.execute("UPDATE chunks SET audience = %s WHERE tenant_id = %s AND agent_id = %s",
                             (values["audiences"], tenant_id, agent.id))
        log.info("Admin: changed assistant %s (%s)", agent.display_name, ", ".join(values))
    return {"id": agent.name}


@router.delete("/agents/{agent_id}", dependencies=[Depends(tenant_admin)])
def delete_agent(agent_id: str):
    """Delete an assistant: it is hidden everywhere and never answers again, but its row, chats
    and documents are kept (deleted_at), so nothing is lost."""
    agent = own_agent(agent_id)
    with get_connection(tenants.current_id()) as conn:
        conn.execute("UPDATE agents SET deleted_at = now(), live = false WHERE id = %s AND tenant_id = %s",
                     (agent.id, tenants.current_id()))
    log.info("Admin: deleted assistant %s (%s)", agent.display_name, agent.name)
    return {"ok": True}


@router.post("/agents/order", dependencies=[Depends(tenant_admin)])
def order_agents(body: OrderIn):
    """The assistants' order on the start screen: the ids in their new order."""
    mine = {agent.name for agent in agents_of(tenants.current_id())}
    if set(body.ids) != mine or len(body.ids) != len(mine):
        raise HTTPException(400, "Send every assistant's id exactly once.")
    with get_connection(tenants.current_id()) as conn:
        for position, agent_id in enumerate(body.ids, start=1):
            conn.execute("UPDATE agents SET position = %s WHERE id = %s AND tenant_id = %s",
                         (position, agent_id, tenants.current_id()))
    return {"ok": True}


# ---------------------------------------------------------------- branding

def branding_out(tenant) -> dict:
    return {"name": tenant.name, "short_name": tenant.short_name, "logo_url": tenant.logo_url or "",
            "brand_primary": tenant.brand_primary, "brand_accent": tenant.brand_accent,
            "brand_dark": tenant.brand_dark, "intro": tenant.intro, "audiences": tenant.audiences}


@router.get("/branding", dependencies=[Depends(tenant_admin)])
def get_branding():
    return branding_out(tenants.current())


@router.put("/branding", dependencies=[Depends(tenant_admin)])
def update_branding(body: BrandingIn):
    """Change the university's name, logo, colours, start screen text and audiences."""
    values = body.model_dump(exclude_unset=True)
    for key in ("brand_primary", "brand_accent", "brand_dark"):
        if key in values and not COLOUR.match(values[key] or ""):
            raise HTTPException(400, "Colours are written like #c4161c.")
    if values.get("logo_url"):
        if not LOGO.match(values["logo_url"]):
            raise HTTPException(400, "The logo must be a PNG, JPEG, WebP or SVG picture.")
    elif "logo_url" in values:
        values["logo_url"] = None  # no logo: the short name is shown
    if "audiences" in values:
        keys = [a["key"] for a in values["audiences"]]
        if len(set(keys)) != len(keys) or not all(AUDIENCE_KEY.match(k) for k in keys):
            raise HTTPException(400, "Audience keys must be different, lower case letters, digits or _.")
        values["audiences"] = psycopg.types.json.Jsonb(values["audiences"])
    if values:
        tenant_id = tenants.current_id()
        with get_connection(tenant_id) as conn:
            conn.execute(f"UPDATE tenants SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s",
                         (*values.values(), tenant_id))
        tenants._by_host.clear()  # the next request reads the new look
        log.info("Admin: changed branding (%s)", ", ".join(values))
    return {"ok": True}


# ---------------------------------------------------------------- users

USER_ROLES = ("tenant_admin", "editor")


def user_out(row) -> dict:
    user_id, email, name, role, active, last_login = row
    return {"id": str(user_id), "email": email, "name": name, "role": role, "active": active,
            "last_login_at": last_login.isoformat() if last_login else None}


@router.get("/users", dependencies=[Depends(tenant_admin)])
def list_users():
    tenant_id = tenants.current_id()
    with get_connection(tenant_id) as conn:
        rows = conn.execute("SELECT id, email, name, role, active, last_login_at FROM users WHERE tenant_id = %s "
                            "ORDER BY role, email", (tenant_id,)).fetchall()
    return [user_out(row) for row in rows]


@router.post("/users", dependencies=[Depends(tenant_admin)])
def create_user(body: UserIn):
    if not body.email or not body.password or body.role not in USER_ROLES:
        raise HTTPException(400, f"Give an email, a password and a role ({' or '.join(USER_ROLES)}).")
    problem = auth.password_problem(body.password)
    if problem:
        raise HTTPException(400, problem)
    email = body.email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+$", email):
        raise HTTPException(400, "That is not an email address.")
    tenant_id = tenants.current_id()
    try:
        with get_connection(tenant_id) as conn, conn.transaction():  # a savepoint: a taken email undoes only this
            user_id = conn.execute("INSERT INTO users (tenant_id, email, name, role, password_hash) "
                                   "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                                   (tenant_id, email, body.name or "", body.role, auth.hash_password(body.password))).fetchone()[0]
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "This email address already has an account.")
    log.info("Admin: new user %s (%s)", email, body.role)
    return {"id": str(user_id)}


@router.put("/users/{user_id}")
def update_user(user_id: str, body: UserIn, session: Session = Depends(tenant_admin)):
    """Change a user's name, role, password or active state. The university always keeps at
    least one active tenant_admin (you cannot remove the last one, also not yourself)."""
    values = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k in ("name", "role", "active")}
    if "role" in values and values["role"] not in USER_ROLES:
        raise HTTPException(400, f"The role must be {' or '.join(USER_ROLES)}.")
    if body.password is not None:
        problem = auth.password_problem(body.password)
        if problem:
            raise HTTPException(400, problem)
        values["password_hash"] = auth.hash_password(body.password)
    tenant_id = tenants.current_id()
    with get_connection(tenant_id) as conn:
        row = conn.execute("SELECT role, active FROM users WHERE id = %s AND tenant_id = %s", (user_id, tenant_id)).fetchone()
        if row is None:
            raise HTTPException(404, "User not found.")
        stays_admin = values.get("role", row[0]) == "tenant_admin" and values.get("active", row[1])
        if row[0] == "tenant_admin" and row[1] and not stays_admin:
            others = conn.execute("SELECT count(*) FROM users WHERE tenant_id = %s AND role = 'tenant_admin' "
                                  "AND active AND id <> %s", (tenant_id, user_id)).fetchone()[0]
            if others == 0:
                raise HTTPException(400, "The university needs at least one active admin.")
        if values:
            conn.execute(f"UPDATE users SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s AND tenant_id = %s",
                         (*values.values(), user_id, tenant_id))
    if values.get("active") is False or "password_hash" in values:
        for token, other in list(auth._sessions.items()):  # log that user out everywhere
            if str(other.user_id) == user_id and other is not session:
                auth.log_out(token)
    return {"ok": True}


# ---------------------------------------------------------------- documents

def document_id(agent: str, filename: str) -> str:
    """A URL-safe id for agent id + file name ("<agent id>/campus.md" -> "YTAw...")."""
    return base64.urlsafe_b64encode(f"{agent}/{filename}".encode()).decode().rstrip("=")


def check_agent(key: str):
    """The assistant a request names (by id, or by a GIU template key); 400 if there is none."""
    agent = find_agent(tenants.current_id(), key)
    if agent is None:
        names = ", ".join(f"{a.display_name} ({a.name})" for a in agents_of(tenants.current_id()))
        raise HTTPException(400, f"Unknown assistant '{key}'. Choose one of: {names}.")
    return agent


def clean_filename(filename: str) -> str:
    """Only a plain .md or .txt file name (no folders): "../x" or "a/b.md" are refused."""
    name = filename.strip()
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "The file name must not contain folders.")
    name = re.sub(r"[^\w.\- ()؀-ۿ]", "_", name)
    if not name.lower().endswith(DOCUMENT_TYPES):
        name += ".md"
    return name


def path_of(folder_name: str, filename: str) -> Path:
    """A file in one of the current tenant's assistant folders (`folder_name`: agents.folder)."""
    folder = (tenants.data_dir(tenants.current()) / folder_name).resolve()
    path = (folder / filename).resolve()
    if path.parent != folder:
        raise HTTPException(400, "Invalid file name.")
    return path


def from_id(doc_id: str):
    """(agent, file name, path) of an existing document; 404 if there is none."""
    try:
        agent_id, _, filename = base64.urlsafe_b64decode(doc_id + "=" * (-len(doc_id) % 4)).decode().partition("/")
    except (binascii.Error, UnicodeDecodeError):
        raise HTTPException(404, "Document not found.")
    if not filename or "/" in filename or not filename.lower().endswith(DOCUMENT_TYPES):
        raise HTTPException(404, "Document not found.")
    agent = next((a for a in agents_of(tenants.current_id()) if a.name == agent_id), None)
    if agent is None:
        raise HTTPException(404, "Document not found.")
    path = path_of(agent.settings.folder, filename)
    if not path.is_file():
        raise HTTPException(404, "Document not found.")
    return agent, filename, path


def delete_chunks(agent: str, filename: str) -> None:
    """Remove the current tenant's chunks of one file (`agent`: the assistant's id)."""
    with get_connection(tenants.current_id()) as conn:
        conn.execute("DELETE FROM chunks WHERE tenant_id = %s AND agent_id = %s AND source = %s",
                     (tenants.current_id(), agent, filename))


def save_and_index(agent, filename: str, content: str) -> int:
    """Write the file and index it again (old chunks first, so an emptied file has none)."""
    path = path_of(agent.settings.folder, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8")
    delete_chunks(agent.name, filename)
    try:
        return ingest_file(path, agent.name, list(agent.allowed_user_types))
    except usage.AllowanceUsedUp as error:
        raise HTTPException(429, f"The document was saved, but not indexed: {error}")
    except (httpx.HTTPError, KeyError) as error:
        log.warning("Admin: re-indexing %s/%s failed: %s", agent.display_name, filename, type(error).__name__)
        raise HTTPException(502, "The document was saved, but re-indexing failed (the embedding service "
                                 "did not answer). Save it again in a moment.")


@router.get("/documents", dependencies=[Depends(university_user)])
def list_documents():
    documents = []
    for agent in agents_of(tenants.current_id()):
        folder = tenants.data_dir(tenants.current()) / agent.settings.folder
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in DOCUMENT_TYPES:
                updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
                documents.append({"id": document_id(agent.name, path.name), "agent": agent.name,
                                  "agent_name": agent.display_name, "folder": agent.settings.folder,
                                  "filename": path.name, "updated_at": updated})
    return documents


@router.get("/documents/{doc_id}", dependencies=[Depends(university_user)])
def get_document(doc_id: str):
    agent, filename, path = from_id(doc_id)
    return {"id": doc_id, "agent": agent.name, "filename": filename,
            "content": path.read_text(encoding="utf-8")}


@router.post("/documents", dependencies=[Depends(university_user)])
def create_document(body: DocumentIn):
    agent, filename = check_agent(body.agent), clean_filename(body.filename)
    if path_of(agent.settings.folder, filename).exists():
        raise HTTPException(409, f"{filename} already exists for this assistant. Edit it instead, or choose another name.")
    chunks = save_and_index(agent, filename, body.content)
    log.info("Admin: added %s/%s (%d chunks)", agent.display_name, filename, chunks)
    return {"id": document_id(agent.name, filename), "chunks": chunks}


@router.put("/documents/{doc_id}", dependencies=[Depends(university_user)])
def update_document(doc_id: str, body: DocumentIn):
    old_agent, old_filename, old_path = from_id(doc_id)
    agent, filename = check_agent(body.agent), clean_filename(body.filename)
    moved = (agent.name, filename) != (old_agent.name, old_filename)
    if moved and path_of(agent.settings.folder, filename).exists():
        raise HTTPException(409, f"{filename} already exists for this assistant. Choose another name.")
    chunks = save_and_index(agent, filename, body.content)
    if moved:  # the document moved to another assistant or got a new name: remove the old one
        old_path.unlink(missing_ok=True)
        delete_chunks(old_agent.name, old_filename)
    log.info("Admin: saved %s/%s (%d chunks)%s", agent.display_name, filename, chunks,
             f", moved from {old_agent.display_name}/{old_filename}" if moved else "")
    return {"id": document_id(agent.name, filename), "chunks": chunks}


@router.delete("/documents/{doc_id}", dependencies=[Depends(university_user)])
def delete_document(doc_id: str):
    agent, filename, path = from_id(doc_id)
    path.unlink()
    delete_chunks(agent.name, filename)
    log.info("Admin: deleted %s/%s", agent.display_name, filename)
    return {"ok": True}
