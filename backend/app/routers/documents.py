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

from app import config
from app.agents import AGENTS
from app.db import get_connection
from app.documents import storage
from app.documents.editor import edit_document
from app.documents.formats import check_file, preview_html
from app.llm.client import LLMError
from app.schemas import DocumentEditRequest, DocumentEditResponse

router = APIRouter()
STOPPED_BY_USER = 499  # the user pressed Stop: nothing is saved (same as /chat)


@router.post("/documents/edit", response_model=DocumentEditResponse)
async def edit(body: DocumentEditRequest, request: Request):
    agent_name = await run_in_threadpool(conversation_agent, body.conversation_id)
    result, info = await run_in_threadpool(run_edit, body, agent_name)
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


def conversation_agent(conversation_id: int) -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT agent FROM conversations WHERE id = %s", (conversation_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Conversation not found. Start a new session.")
    return row[0]


def run_edit(body: DocumentEditRequest, agent_name: str):
    """Edit a new upload or the current document; errors become HTTP errors."""
    upload = None
    if body.document:
        try:
            upload = (body.document.filename, base64.b64decode(body.document.data_base64, validate=True))
        except binascii.Error:
            raise HTTPException(400, "The file could not be read. Please try uploading it again.")
    try:
        return edit_conversation_document(body.conversation_id, body.instruction, upload,
                                          body.document_token, agent_name)
    except ValueError as error:  # a bad file or an impossible request: tell the user why
        raise HTTPException(400, str(error))
    except (httpx.HTTPError, LLMError):
        raise HTTPException(502, "The assistant is temporarily unavailable. Please try again.")


def edit_conversation_document(conversation_id: int, instruction: str, upload: tuple[str, bytes] | None,
                               token: str | None, agent_name: str):
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
    agent = AGENTS[agent_name]
    result = edit_document(data, ext, instruction, [config.DOC_EDIT_MODEL, *config.DOC_EDIT_BACKUP_MODELS],
                           [agent.vision_model, *agent.vision_backup_models])
    return result, storage.current(conversation_id)


def save_messages(body: DocumentEditRequest, filename: str, answer: str) -> int:
    """Store the instruction and the answer (the document itself is not stored in the database)."""
    with get_connection() as conn:
        conn.execute("INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
                     (body.conversation_id, f"{body.instruction}\n[Edit document: {filename}]"))
        return conn.execute("INSERT INTO messages (conversation_id, role, content) "
                            "VALUES (%s, 'assistant', %s) RETURNING id",
                            (body.conversation_id, answer)).fetchone()[0]


@router.get("/documents/{conversation_id}/{token}")
def download(conversation_id: int, token: str):
    found = storage.file_for_download(conversation_id, token)
    if found is None:
        raise HTTPException(404, "This file is no longer available. Edit the document again to get a new link.")
    path, name, media_type = found
    return FileResponse(path, media_type=media_type, filename=name, headers={"Cache-Control": "no-store"})


@router.get("/documents/{conversation_id}/{token}/view")
def view(conversation_id: int, token: str):
    found = storage.file_for_download(conversation_id, token)
    if found is None:
        raise HTTPException(404, "This file is no longer available. Edit the document again to get a new link.")
    path, name, media_type = found
    safe = {"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff"}
    if path.suffix in (".pdf", ".txt", ".md"):  # the browser shows these itself
        media = "text/plain; charset=utf-8" if path.suffix == ".md" else media_type
        return FileResponse(path, media_type=media, filename=name, content_disposition_type="inline", headers=safe)
    return HTMLResponse(preview_html(path.suffix, path.read_bytes(), name), headers=safe)


@router.delete("/documents/{conversation_id}/{token}")
def stop_editing(conversation_id: int, token: str):
    if storage.is_latest(conversation_id, token):
        storage.remove(conversation_id)
    return {"ok": True}
