"""Admin routes: manage the documents the agents answer from: the current tenant's folder
(GIU: data/raw/<agent>/*.md|*.txt, other tenants: data/tenants/<slug>/<agent>/).

POST   /admin/login              {password} -> {token}
GET    /admin/documents          [{id, agent, filename, updated_at}]
GET    /admin/documents/{id}     {id, agent, filename, content}
POST   /admin/documents          {agent, filename, content} -> {id, chunks}
PUT    /admin/documents/{id}     {agent, filename, content} -> {id, chunks}   (changing the agent moves it)
DELETE /admin/documents/{id}

Every change is re-indexed at once (chunks + embeddings, like `python -m scripts.ingest`),
so the agents answer from the new text right away.

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
from app.agents.directory import AGENT_DIRECTORY
from app.db import get_connection
from scripts.ingest import ingest_file

router = APIRouter(prefix="/admin")
log = logging.getLogger("uvicorn.error")

DOCUMENT_TYPES = (".md", ".txt")
AUDIENCES = {agent.key: list(agent.user_types) for agent in AGENT_DIRECTORY}  # who may read each agent's documents
_tokens: dict[str, float] = {}  # token -> expiry time (kept in memory: a restart logs everyone out)
_token_tenants: dict[str, object] = {}  # token -> id of the tenant it was issued for


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class DocumentIn(BaseModel):
    agent: str
    filename: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=config.ADMIN_MAX_DOCUMENT_CHARS)


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


# ---------------------------------------------------------------- documents

def document_id(agent: str, filename: str) -> str:
    """A URL-safe id for agent + file name ("labs_research/campus.md" -> "bGFic1...")."""
    return base64.urlsafe_b64encode(f"{agent}/{filename}".encode()).decode().rstrip("=")


def check_agent(agent: str) -> str:
    if agent not in AUDIENCES:
        raise HTTPException(400, f"Unknown agent '{agent}'. Choose one of: {', '.join(AUDIENCES)}.")
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
    folder = (tenants.data_dir(tenants.current()) / agent).resolve()
    path = (folder / filename).resolve()
    if path.parent != folder:
        raise HTTPException(400, "Invalid file name.")
    return path


def from_id(doc_id: str) -> tuple[str, str, Path]:
    """(agent, file name, path) of an existing document; 404 if there is none."""
    try:
        agent, _, filename = base64.urlsafe_b64decode(doc_id + "=" * (-len(doc_id) % 4)).decode().partition("/")
    except (binascii.Error, UnicodeDecodeError):
        raise HTTPException(404, "Document not found.")
    if agent not in AUDIENCES or not filename or "/" in filename or not filename.lower().endswith(DOCUMENT_TYPES):
        raise HTTPException(404, "Document not found.")
    path = path_of(agent, filename)
    if not path.is_file():
        raise HTTPException(404, "Document not found.")
    return agent, filename, path


def delete_chunks(agent: str, filename: str) -> None:
    """Remove the current tenant's chunks of one file."""
    with get_connection(tenants.current_id()) as conn:
        conn.execute("DELETE FROM chunks WHERE tenant_id = %s AND agent = %s AND source = %s",
                     (tenants.current_id(), agent, filename))


def save_and_index(agent: str, filename: str, content: str) -> int:
    """Write the file and index it again (old chunks first, so an emptied file has none)."""
    path = path_of(agent, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8")
    delete_chunks(agent, filename)
    try:
        return ingest_file(path, agent, AUDIENCES[agent])
    except (httpx.HTTPError, KeyError) as error:
        log.warning("Admin: re-indexing %s/%s failed: %s", agent, filename, type(error).__name__)
        raise HTTPException(502, "The document was saved, but re-indexing failed (the embedding service "
                                 "did not answer). Save it again in a moment.")


@router.get("/documents", dependencies=[Depends(require_admin)])
def list_documents():
    documents = []
    for agent in AUDIENCES:
        folder = tenants.data_dir(tenants.current()) / agent
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in DOCUMENT_TYPES:
                updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
                documents.append({"id": document_id(agent, path.name), "agent": agent,
                                  "filename": path.name, "updated_at": updated})
    return documents


@router.get("/documents/{doc_id}", dependencies=[Depends(require_admin)])
def get_document(doc_id: str):
    agent, filename, path = from_id(doc_id)
    return {"id": doc_id, "agent": agent, "filename": filename, "content": path.read_text(encoding="utf-8")}


@router.post("/documents", dependencies=[Depends(require_admin)])
def create_document(body: DocumentIn):
    agent, filename = check_agent(body.agent), clean_filename(body.filename)
    if path_of(agent, filename).exists():
        raise HTTPException(409, f"{filename} already exists for this agent. Edit it instead, or choose another name.")
    chunks = save_and_index(agent, filename, body.content)
    log.info("Admin: added %s/%s (%d chunks)", agent, filename, chunks)
    return {"id": document_id(agent, filename), "chunks": chunks}


@router.put("/documents/{doc_id}", dependencies=[Depends(require_admin)])
def update_document(doc_id: str, body: DocumentIn):
    old_agent, old_filename, old_path = from_id(doc_id)
    agent, filename = check_agent(body.agent), clean_filename(body.filename)
    moved = (agent, filename) != (old_agent, old_filename)
    if moved and path_of(agent, filename).exists():
        raise HTTPException(409, f"{filename} already exists for this agent. Choose another name.")
    chunks = save_and_index(agent, filename, body.content)
    if moved:  # the document moved to another agent or got a new name: remove the old one
        old_path.unlink(missing_ok=True)
        delete_chunks(old_agent, old_filename)
    log.info("Admin: saved %s/%s (%d chunks)%s", agent, filename, chunks,
             f", moved from {old_agent}/{old_filename}" if moved else "")
    return {"id": document_id(agent, filename), "chunks": chunks}


@router.delete("/documents/{doc_id}", dependencies=[Depends(require_admin)])
def delete_document(doc_id: str):
    agent, filename, path = from_id(doc_id)
    path.unlink()
    delete_chunks(agent, filename)
    log.info("Admin: deleted %s/%s", agent, filename)
    return {"ok": True}
