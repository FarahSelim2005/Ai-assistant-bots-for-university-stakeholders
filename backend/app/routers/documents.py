"""Document editor routes.

POST   /documents/edit                         edit a new upload or the chat's current document
GET    /documents/{conversation_id}/{token}    download one version (random token from the edit answer)
GET    /documents/{conversation_id}/{token}/view   show it in the browser (PDF and text as they are,
                                                Word / PowerPoint / Excel as a simple HTML page)
DELETE /documents/{conversation_id}/{token}    stop editing: delete the chat's document files

Conversation ids are simple numbers, so every request about an existing document also
needs the random token of its latest version (only the browser that edited it has it).

The instruction and a short answer are saved as chat messages, like normal questions.
"""
import base64
import binascii

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from starlette.concurrency import run_in_threadpool

from app import config, tenants
from app.agents import load_agent
from app.db import get_connection
from app.documents import storage
from app.documents.editor import edit_document
from app.documents.formats import check_file, preview_html
from app.llm.client import LLMError
from app.schemas import DocumentEditRequest, DocumentEditResponse

router = APIRouter()
FILE_GONE = ("This file is no longer available: files are kept for one hour, and a new chat deletes them. "
             "Send the document again to get a new link.")
STOPPED_BY_USER = 499  # the user pressed Stop: nothing is saved (same as /chat)


@router.post("/documents/edit", response_model=DocumentEditResponse)
async def edit(body: DocumentEditRequest, request: Request):
    agent = await run_in_threadpool(require_conversation, body.conversation_id)
    result, info = await run_in_threadpool(run_edit, body, agent)
    if await request.is_disconnected():
        return Response(status_code=STOPPED_BY_USER)
    saved = await run_in_threadpool(storage.save_version, body.conversation_id, result.data, result.extension)
    answer = result.summary + "".join(f"\n- {note}" for note in result.notes)
    message_id = await run_in_threadpool(save_messages, body, info["filename"], answer)
    return DocumentEditResponse(
        answer=answer,
        file={"filename": saved["filename"], "download_name": saved["download_name"],
              "url": f"/documents/{body.conversation_id}/{saved['token']}", "version": saved["version"]},
        changes=result.changes,
        message_id=message_id,
    )


def conversation_agent(conversation_id: int):
    """The agent id of a conversation of the current tenant (None: no such conversation here)."""
    with get_connection(tenants.current_id()) as conn:
        row = conn.execute("SELECT agent_id FROM conversations WHERE id = %s AND tenant_id = %s",
                           (conversation_id, tenants.current_id())).fetchone()
    return row[0] if row else None


def require_conversation(conversation_id: int):
    """The assistant of a conversation of the current tenant, which must edit documents (the
    "editor" skill; 403 otherwise)."""
    agent = conversation_assistant(conversation_id)
    if not agent.edits_documents:
        raise HTTPException(403, "This assistant does not edit documents.")
    return agent


def conversation_assistant(conversation_id: int):
    """The assistant of a conversation of the current tenant (404 / 410 if there is none)."""
    agent_id = conversation_agent(conversation_id)
    if agent_id is None:  # also another university's conversation
        raise HTTPException(404, "Conversation not found. Start a new session.")
    agent = load_agent(tenants.current_id(), agent_id)
    if agent is None or not agent.live:
        raise HTTPException(410, "This assistant is no longer available. Start a new chat.")
    return agent


def run_edit(body: DocumentEditRequest, agent):
    """Edit a new upload or the current document; errors become HTTP errors."""
    upload = None
    if body.document:
        try:
            upload = (body.document.filename, base64.b64decode(body.document.data_base64, validate=True))
        except binascii.Error:
            raise HTTPException(400, "The file could not be read. Please try uploading it again.")
    try:
        return edit_conversation_document(body.conversation_id, body.instruction, upload,
                                          body.document_token, agent)
    except ValueError as error:  # a bad file or an impossible request: tell the user why
        raise HTTPException(400, str(error))
    except (httpx.HTTPError, LLMError):
        raise HTTPException(502, "The assistant is temporarily unavailable. Please try again.")


def edit_conversation_document(conversation_id: int, instruction: str, upload: tuple[str, bytes] | None,
                               token: str | None, agent):
    """Edit an uploaded file ((filename, bytes), stored as version 0) or the chat's current
    document (needs the token of its latest version). Also used by POST /chat. Returns
    (EditResult, stored info); raises ValueError, LLMError or httpx errors."""
    storage.remove_old_files()
    if upload:
        filename, data = upload
        ext = check_file(filename, data, config.DOC_EDIT_MAX_MB)
        storage.save_version(conversation_id, data, ext, filename=filename)
    elif not storage.is_latest(conversation_id, token or ""):
        raise ValueError("There is no document to edit in this chat any more (files are kept for "
                         f"{config.DOC_EDIT_KEEP_MINUTES} minutes). Attach it again.")
    data, ext = storage.latest_file(conversation_id)
    result = edit_document(data, ext, instruction, [config.DOC_EDIT_MODEL, *config.DOC_EDIT_BACKUP_MODELS],
                           [agent.vision_model, *agent.vision_backup_models])
    return result, storage.current(conversation_id)


def save_messages(body: DocumentEditRequest, filename: str, answer: str) -> int:
    """Store the instruction and the answer (the document itself is not stored in the database)."""
    tenant_id = tenants.current_id()
    with get_connection(tenants.current_id()) as conn:
        conn.execute("INSERT INTO messages (tenant_id, conversation_id, role, content) VALUES (%s, %s, 'user', %s)",
                     (tenant_id, body.conversation_id, f"{body.instruction}\n[Edit document: {filename}]"))
        return conn.execute("INSERT INTO messages (tenant_id, conversation_id, role, content) "
                            "VALUES (%s, %s, 'assistant', %s) RETURNING id",
                            (tenant_id, body.conversation_id, answer)).fetchone()[0]


def file_of(conversation_id: int, token: str):
    """(path, name, media type) of a stored version; 404 if it is gone or the conversation
    belongs to another university (the files themselves are kept per conversation id)."""
    found = storage.file_for_download(conversation_id, token)
    if found is None or conversation_agent(conversation_id) is None:
        raise HTTPException(404, FILE_GONE)
    return found


@router.get("/documents/{conversation_id}/{token}")
def download(conversation_id: int, token: str):
    path, name, media_type = file_of(conversation_id, token)
    return FileResponse(path, media_type=media_type, filename=name, headers={"Cache-Control": "no-store"})


@router.get("/documents/{conversation_id}/{token}/view")
def view(conversation_id: int, token: str):
    path, name, media_type = file_of(conversation_id, token)
    safe = {"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff"}
    if path.suffix in (".pdf", ".txt", ".md"):  # the browser shows these itself
        media = "text/plain; charset=utf-8" if path.suffix == ".md" else media_type
        return FileResponse(path, media_type=media, filename=name, content_disposition_type="inline", headers=safe)
    return HTMLResponse(preview_html(path.suffix, path.read_bytes(), name), headers=safe)


@router.delete("/documents/{conversation_id}/{token}")
def stop_editing(conversation_id: int, token: str):
    if storage.is_latest(conversation_id, token) and conversation_agent(conversation_id) is not None:
        storage.remove(conversation_id)
    return {"ok": True}
