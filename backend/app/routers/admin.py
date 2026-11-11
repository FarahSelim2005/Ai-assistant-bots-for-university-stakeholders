"""Admin routes: the current university's assistants, and the documents they answer from
(one folder per assistant id: GIU data/raw/<id>/*.md|*.txt, other tenants
data/tenants/<slug>/<id>/).

POST   /admin/login              {password} -> {token}
GET    /admin/agents             [{id, key, name, ..., live}]
GET    /admin/agent-templates    [{key, name, summary, ...}]   ready-made assistants to start from
POST   /admin/agents             {template_key?, name?, ...} -> {id}   a new assistant (from a template or not)
PUT    /admin/agents/{id}        {name?, description?, ..., live?} -> {id}
GET    /admin/documents          [{id, agent, agent_id, agent_name, filename, updated_at}]
GET    /admin/documents/{id}     {id, agent, agent_id, filename, content}
POST   /admin/documents          {agent, filename, content} -> {id, chunks}
PUT    /admin/documents/{id}     {agent, filename, content} -> {id, chunks}   (changing the agent moves it)
DELETE /admin/documents/{id}

`agent` in a document request is the assistant's id, or the template key of one of GIU's
("labs_research"), which the current admin page sends; lists name it the same way.

Every document change is re-indexed at once (chunks + embeddings, like `python -m scripts.ingest`),
so the assistants answer from the new text right away.

Login: with ADMIN_PASSWORD in backend/.env, every route except login needs the header
"Authorization: Bearer <token>" (tokens last ADMIN_TOKEN_HOURS). A token only works for the
tenant (host) it was issued on. Without a password the routes are open, for local
development only (a warning is logged at start-up).
"""
import base64
import binascii
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import config, tenants
from app.agents import agents_of, find_agent, load_agent, public_key
from app.agents.templates import ANSWER_MODES, AUDIENCES, PROMPT_MODES, SKILLS
from app.db import get_connection
from scripts.ingest import ingest_file

router = APIRouter(prefix="/admin")
log = logging.getLogger("uvicorn.error")

DOCUMENT_TYPES = (".md", ".txt")
_tokens: dict[str, float] = {}  # token -> expiry time (kept in memory: a restart logs everyone out)
_token_tenants: dict[str, object] = {}  # token -> id of the tenant it was issued for


class LoginRequest(BaseModel):
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
    audiences: list[str] | None = Field(default=None, min_length=1, max_length=2)
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



# ---------------------------------------------------------------- login

@router.post("/login")
async def login(body: LoginRequest):
    if not config.ADMIN_PASSWORD:
        raise HTTPException(503, "No admin password is set up. Add ADMIN_PASSWORD to backend/.env.")
    if not secrets.compare_digest(body.password.encode(), config.ADMIN_PASSWORD.encode()):
        await run_in_threadpool(time.sleep, 1)  # slows down password guessing
        raise HTTPException(401, "Wrong password.")
    now = time.time()
    for token, expiry in list(_tokens.items()):  # forget expired tokens
        if expiry < now:
            del _tokens[token]
            _token_tenants.pop(token, None)
    token = secrets.token_urlsafe(32)
    _tokens[token] = now + config.ADMIN_TOKEN_HOURS * 3600
    _token_tenants[token] = tenants.current_id()
    return {"token": token}


def require_admin(authorization: str = Header(default="")) -> None:
    """Every route below needs a valid login token of this tenant (unless no password is set up)."""
    if not config.ADMIN_PASSWORD:
        return
    token = authorization.removeprefix("Bearer ").strip()
    if _tokens.get(token, 0) < time.time() or _token_tenants.get(token) != tenants.current_id():
        raise HTTPException(401, "Please log in again.")


# ---------------------------------------------------------------- assistants

def agent_out(agent) -> dict:
    s = agent.settings
    return {"id": agent.name, "key": public_key(agent), "template_key": s.template_key, "name": s.name,
            "summary": s.summary, "subtitle": s.subtitle, "description": s.description, "audiences": list(s.audiences),
            "answer_mode": s.answer_mode, "prompt_mode": s.prompt_mode, "instructions": s.instructions,
            "fallback_en": s.fallback_en,
            "fallback_ar": s.fallback_ar, "welcome": s.welcome, "placeholder": s.placeholder,
            "examples": list(s.examples), "skills": list(s.skills), "max_answer_tokens": s.max_answer_tokens,
            "model": s.model, "backup_models": list(s.backup_models), "similarity_threshold": s.similarity_threshold,
            "position": s.position, "live": s.live,
            # The skills that work here (cv needs a trained CV model, map a campus map).
            "active_skills": [k for k, on in [("files", agent.reads_files), ("images", agent.reads_images),
                                              ("cv", agent.rewrites_cvs), ("editor", agent.edits_documents),
                                              ("map", agent.campus_map), ("voice", agent.has_skill("voice"))] if on]}


def checked_settings(values: dict) -> dict:
    """The given settings, refused (400) when one is not allowed."""
    if values.get("audiences") is not None and not set(values["audiences"]) <= set(AUDIENCES):
        raise HTTPException(400, f"Audiences must be {' and/or '.join(AUDIENCES)}.")
    if values.get("answer_mode") is not None and values["answer_mode"] not in ANSWER_MODES:
        raise HTTPException(400, f"The answer mode must be one of: {', '.join(ANSWER_MODES)}.")
    if values.get("prompt_mode") is not None and values["prompt_mode"] not in PROMPT_MODES:
        raise HTTPException(400, f"The prompt mode must be one of: {', '.join(PROMPT_MODES)}.")
    skills = values.get("skills")
    if skills is not None:
        unknown = set(skills) - set(SKILLS)
        if unknown:
            raise HTTPException(400, f"Unknown skills: {', '.join(sorted(unknown))}. Choose from: {', '.join(SKILLS)}.")
        if "cv" in skills and not tenants.current().has_cv_model:
            raise HTTPException(400, "CV rewrites need a CV model trained for this university.")
    if values.get("name") is not None and not values["name"].strip():
        raise HTTPException(400, "The name must not be empty.")
    return values


@router.get("/agents", dependencies=[Depends(require_admin)])
def list_agents():
    return [agent_out(agent) for agent in agents_of(tenants.current_id())]


@router.get("/agent-templates", dependencies=[Depends(require_admin)])
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


@router.post("/agents", dependencies=[Depends(require_admin)])
def create_agent(body: AgentIn):
    """A new assistant: the template's settings (if one is given), changed by the fields sent.
    It goes last in the list unless a position is given. A template's "cv" skill is left out
    at a university without a trained CV model."""
    tenant_id = tenants.current_id()
    with get_connection(tenant_id) as conn:
        settings = {}
        if body.template_key:
            row = conn.execute(f"SELECT {', '.join(TEMPLATE_FIELDS)} FROM agent_templates WHERE key = %s",
                               (body.template_key,)).fetchone()
            if row is None:
                raise HTTPException(400, f"Unknown template '{body.template_key}'.")
            settings = dict(zip(TEMPLATE_FIELDS, row))
            if not tenants.current().has_cv_model:
                settings["skills"] = [skill for skill in settings["skills"] if skill != "cv"]
        settings.update({k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "template_key"})
        checked_settings(settings)
        if not settings.get("name"):
            raise HTTPException(400, "Give the assistant a name (or start from a template).")
        if "position" not in settings:
            settings["position"] = conn.execute("SELECT coalesce(max(position), 0) + 1 FROM agents WHERE tenant_id = %s",
                                                (tenant_id,)).fetchone()[0]
        columns = ["tenant_id", "template_key", *settings]
        agent_id = conn.execute(
            f"INSERT INTO agents ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id",
            (tenant_id, body.template_key, *settings.values())).fetchone()[0]
    log.info("Admin: new assistant %s (%s)", settings["name"], agent_id)
    return {"id": str(agent_id)}


@router.put("/agents/{agent_id}", dependencies=[Depends(require_admin)])
def update_agent(agent_id: str, body: AgentIn):
    agent = load_agent(tenants.current_id(), agent_id)
    if agent is None:
        raise HTTPException(404, "Assistant not found.")
    values = checked_settings({k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "template_key"})
    if values:
        with get_connection(tenants.current_id()) as conn:
            conn.execute(f"UPDATE agents SET {', '.join(f'{k} = %s' for k in values)} WHERE id = %s AND tenant_id = %s",
                         (*values.values(), agent.id, tenants.current_id()))
        log.info("Admin: changed assistant %s (%s)", agent.display_name, ", ".join(values))
    return {"id": agent.name}


# ---------------------------------------------------------------- documents

def document_id(agent: str, filename: str) -> str:
    """A URL-safe id for agent id + file name ("<agent id>/campus.md" -> "YTAw...")."""
    return base64.urlsafe_b64encode(f"{agent}/{filename}".encode()).decode().rstrip("=")


def check_agent(key: str):
    """The assistant a request names (by id, or by a GIU template key); 400 if there is none."""
    agent = find_agent(tenants.current_id(), key)
    if agent is None:
        names = ", ".join(f"{a.display_name} ({public_key(a)})" for a in agents_of(tenants.current_id()))
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


def path_of(agent: str, filename: str) -> Path:
    """The file of an assistant (`agent`: its id) in the current tenant's folder."""
    folder = (tenants.data_dir(tenants.current()) / agent).resolve()
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
    path = path_of(agent.name, filename)
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
    path = path_of(agent.name, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8")
    delete_chunks(agent.name, filename)
    try:
        return ingest_file(path, agent.name, list(agent.allowed_user_types))
    except (httpx.HTTPError, KeyError) as error:
        log.warning("Admin: re-indexing %s/%s failed: %s", agent.display_name, filename, type(error).__name__)
        raise HTTPException(502, "The document was saved, but re-indexing failed (the embedding service "
                                 "did not answer). Save it again in a moment.")


@router.get("/documents", dependencies=[Depends(require_admin)])
def list_documents():
    documents = []
    for agent in agents_of(tenants.current_id()):
        folder = tenants.data_dir(tenants.current()) / agent.name
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in DOCUMENT_TYPES:
                updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
                documents.append({"id": document_id(agent.name, path.name), "agent": public_key(agent),
                                  "agent_id": agent.name, "agent_name": agent.display_name,
                                  "filename": path.name, "updated_at": updated})
    return documents


@router.get("/documents/{doc_id}", dependencies=[Depends(require_admin)])
def get_document(doc_id: str):
    agent, filename, path = from_id(doc_id)
    return {"id": doc_id, "agent": public_key(agent), "agent_id": agent.name, "filename": filename,
            "content": path.read_text(encoding="utf-8")}


@router.post("/documents", dependencies=[Depends(require_admin)])
def create_document(body: DocumentIn):
    agent, filename = check_agent(body.agent), clean_filename(body.filename)
    if path_of(agent.name, filename).exists():
        raise HTTPException(409, f"{filename} already exists for this assistant. Edit it instead, or choose another name.")
    chunks = save_and_index(agent, filename, body.content)
    log.info("Admin: added %s/%s (%d chunks)", agent.display_name, filename, chunks)
    return {"id": document_id(agent.name, filename), "chunks": chunks}


@router.put("/documents/{doc_id}", dependencies=[Depends(require_admin)])
def update_document(doc_id: str, body: DocumentIn):
    old_agent, old_filename, old_path = from_id(doc_id)
    agent, filename = check_agent(body.agent), clean_filename(body.filename)
    moved = (agent.name, filename) != (old_agent.name, old_filename)
    if moved and path_of(agent.name, filename).exists():
        raise HTTPException(409, f"{filename} already exists for this assistant. Choose another name.")
    chunks = save_and_index(agent, filename, body.content)
    if moved:  # the document moved to another assistant or got a new name: remove the old one
        old_path.unlink(missing_ok=True)
        delete_chunks(old_agent.name, old_filename)
    log.info("Admin: saved %s/%s (%d chunks)%s", agent.display_name, filename, chunks,
             f", moved from {old_agent.display_name}/{old_filename}" if moved else "")
    return {"id": document_id(agent.name, filename), "chunks": chunks}


@router.delete("/documents/{doc_id}", dependencies=[Depends(require_admin)])
def delete_document(doc_id: str):
    agent, filename, path = from_id(doc_id)
    path.unlink()
    delete_chunks(agent.name, filename)
    log.info("Admin: deleted %s/%s", agent.display_name, filename)
    return {"ok": True}
