"""POST /chat: answer a question in a conversation and store both messages.

The message is handled in one of three ways, decided automatically:
- a request to change an attached file ("restructure my CV", "translate this report") or
  the chat's open document ("now make it shorter"): the document editor edits it, and the
  answer comes with the file to view and download;
- a CV restructure in the Internship & Career agent: the fine-tuned CV model answers as
  before, and its CV is also made into a PDF (and a Word file) to view and download;
- anything else, including questions about an attached file: the agent answers.

If the user presses "Stop" in the browser while the answer is being made, the browser
stops waiting. The answer is then thrown away instead of saved, so a stopped question
does not appear in the conversation history (and does not affect follow-up questions).
"""
import base64
import binascii
import re
from dataclasses import asdict, dataclass, field

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.agents import AGENTS
from app.agents.base import AgentResponse
from app.attachments import read_attachment
from app.db import get_connection
from app.documents import storage
from app.documents.cv_file import cv_docx, cv_pdf, docx_to_cv_text, is_restructured_cv
from app.documents.editor import is_edit_request
from app.documents.formats import EDITABLE_TYPES
from app.llm.client import LLMError
from app.routers.documents import edit_conversation_document
from app.schemas import ChatRequest, ChatResponse

router = APIRouter()

HISTORY_SIZE = 4  # earlier messages sent along so follow-up questions make sense
STOPPED_BY_USER = 499  # non-standard "client closed request" status, never seen by the browser
CV_WORDS = re.compile(r"\b(cv|c\.v\.|resume|résumé)\b|سي في|السي في|السيرة", re.IGNORECASE)


@dataclass
class Outcome:
    response: AgentResponse
    files: list[tuple[bytes, str, str | None]] = field(default_factory=list)  # (content, extension, download name)
    new_document: str | None = None  # file name, when the files start a new document (a CV)
    cv: bool = False                 # the files are a restructured CV (PDF + Word)
    changes: list[dict] = field(default_factory=list)


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request):
    # The work itself is slow, blocking code (database, model calls), so it runs in a
    # worker thread; meanwhile this function can notice when the user pressed "Stop".
    outcome = await run_in_threadpool(answer_question, body)
    if await request.is_disconnected():
        return Response(status_code=STOPPED_BY_USER)
    result = outcome.response
    file = await run_in_threadpool(store_files, body.conversation_id, outcome) if outcome.files else None
    message_id = await run_in_threadpool(save_messages, body, result.answer)
    return ChatResponse(
        answer=result.answer,
        sources=result.sources,
        locations=[asdict(location) for location in result.locations],
        places=[{"key": place.key, "name": place.name} for place in result.places],
        redirect=asdict(result.redirect) if result.redirect else None,
        message_id=message_id,
        file=file,
        changes=outcome.changes,
    )


def answer_question(body: ChatRequest) -> Outcome:
    """Load the conversation and its recent messages, then answer, edit or restructure."""
    with get_connection() as conn:
        conversation = conn.execute(
            "SELECT user_type, agent FROM conversations WHERE id = %s",
            (body.conversation_id,),
        ).fetchone()
        if conversation is None:
            raise HTTPException(404, "Conversation not found. Start a new session.")
        user_type, agent_name = conversation

        # Last messages, newest first in SQL, then reversed into chronological order.
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = %s "
            "ORDER BY id DESC LIMIT %s",
            (body.conversation_id, HISTORY_SIZE),
        ).fetchall()
    history = [{"role": role, "content": content} for role, content in reversed(rows)]

    try:
        wants_edit = is_edit_request(body.query)
        if body.attachment:
            filename = body.attachment.filename
            extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            is_cv = agent_name == "internship_career" and (CV_WORDS.search(body.query) or CV_WORDS.search(filename))
            if wants_edit and not is_cv and extension in EDITABLE_TYPES:
                return edit(body, agent_name, upload=(filename, decode(body.attachment.data_base64)))
            attachment = read_attachment(filename, body.attachment.data_base64)
            response = AGENTS[agent_name].run(body.query, user_type, history, attachment)
            if is_cv and wants_edit and is_restructured_cv(response.answer):
                return cv_files(response, filename)
            return Outcome(response)
        if wants_edit and body.document_token and storage.is_latest(body.conversation_id, body.document_token):
            return edit(body, agent_name, upload=None)
        return Outcome(AGENTS[agent_name].run(body.query, user_type, history, None))
    except ValueError as error:  # a bad attachment or a broken agent rule
        raise HTTPException(400, str(error))
    except (httpx.HTTPError, LLMError):  # OpenRouter unreachable, an error, or no answer
        raise HTTPException(502, "The assistant is temporarily unavailable. Please try again.")


def decode(data_base64: str) -> bytes:
    try:
        return base64.b64decode(data_base64, validate=True)
    except binascii.Error:
        raise ValueError("The file could not be read. Please try uploading it again.")


def edit(body: ChatRequest, agent_name: str, upload) -> Outcome:
    """The document editor's answer: what changed, and the edited file."""
    result, info = edit_conversation_document(body.conversation_id, body.query, upload, body.document_token, agent_name)
    answer = result.summary + "".join(f"\n- {note}" for note in result.notes)
    files = [(result.data, result.extension, None)]
    if upload is None and info.get("cv") and result.extension == ".docx":
        # A restructured CV: its Word version was edited; make a new PDF of it as well.
        stem = info["filename"].rsplit(".", 1)[0]
        files = [(cv_pdf(docx_to_cv_text(result.data)), ".pdf", f"{stem}_restructured.pdf"),
                 (result.data, ".docx", f"{stem}_restructured.docx")]
    return Outcome(AgentResponse(answer=answer, sources=[]), files=files, changes=result.changes)


def cv_files(response: AgentResponse, filename: str) -> Outcome:
    """The restructured CV as a PDF (to view and download) and a Word file (to change)."""
    stem = storage.safe_name(filename).rsplit(".", 1)[0]
    return Outcome(response, new_document=f"{stem}.pdf", cv=True, files=[
        (cv_pdf(response.answer), ".pdf", f"{stem}_restructured.pdf"),
        (cv_docx(response.answer), ".docx", f"{stem}_restructured.docx"),
    ])


def store_files(conversation_id: int, outcome: Outcome) -> dict:
    """Save the new file(s) as the chat's document; the links for the answer. The last file
    (the Word file of a CV) is the one the next edit request changes."""
    saved = []
    for index, (data, extension, name) in enumerate(outcome.files):
        start = outcome.new_document if index == 0 else None
        saved.append(storage.save_version(conversation_id, data, extension, filename=start, name=name, cv=outcome.cv))
    main, latest = saved[0], saved[-1]
    url = f"/documents/{conversation_id}/{main['token']}"
    word = saved[1] if len(saved) > 1 else None
    return {"filename": main["filename"], "download_name": main["download_name"], "url": url,
            "view_url": url + "/view", "version": latest["version"], "token": latest["token"],
            "word_url": f"/documents/{conversation_id}/{word['token']}" if word else None,
            "word_name": word["download_name"] if word else None}


def save_messages(body: ChatRequest, answer: str) -> int:
    """Store the question and the answer; returns the answer's message id (for feedback)."""
    # The file itself is not stored; the message only records its name.
    user_message = body.query
    if body.attachment:
        user_message += f"\n[Attached file: {body.attachment.filename}]"

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
            (body.conversation_id, user_message),
        )
        return conn.execute(
            "INSERT INTO messages (conversation_id, role, content) "
            "VALUES (%s, 'assistant', %s) RETURNING id",
            (body.conversation_id, answer),
        ).fetchone()[0]
