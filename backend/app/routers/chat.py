"""POST /chat: answer a question in a conversation and store both messages.

The message is handled in one of three ways, decided automatically:
- a request to change an attached file ("restructure my CV", "translate this report") or
  the chat's open document ("now make it shorter"): the document editor edits it, and the
  answer comes with the file to view and download;
- a CV restructure in the Internship & Career agent: the fine-tuned CV model rewrites the CV;
  the CV becomes a PDF (and a Word file) to view and download, and its CV ANALYSIS (rating,
  changes, what to improve) is the chat message;
- anything else, including questions about an attached file: the agent answers.
Several files sent together are only asked about ("compare these"); they are read as one
attachment. Files are edited, converted or restructured one at a time.

If the user presses "Stop" in the browser while the answer is being made, the browser
stops waiting. The answer is then thrown away instead of saved, so a stopped question
does not appear in the conversation history (and does not affect follow-up questions).
"""
import base64
import binascii
import re
from dataclasses import asdict, dataclass, field, replace

import httpx
import pymupdf
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app import config
from app.agents import AGENTS
from app.agents.base import AgentResponse
from app.attachments import combine_attachments, read_attachment
from app.campus import BUILDINGS
from app.db import get_connection
from app.documents import storage
from app.documents.cv_analysis import check_length
from app.documents.cv_file import (cv_docx, cv_pdf, docx_to_cv_text, is_arabic, is_one_page_target,
                                   is_restructured_cv, split_cv)
from app.agents.internship_career import CV_REWRITE_WORDS
from app.documents.editor import is_edit_request, is_pdf_request
from app.documents.formats import EDITABLE_TYPES, check_file, document_pdf
from app.llm.client import LLMError
from app.routers.documents import edit_conversation_document
from app.schemas import ChatRequest, ChatResponse

router = APIRouter()

HISTORY_SIZE = 4  # earlier messages sent along so follow-up questions make sense
STOPPED_BY_USER = 499  # non-standard "client closed request" status, never seen by the browser
CV_WORDS = re.compile(r"\b(cv|c\.v\.|resume|résumé)\b|سي في|السي في|السيرة", re.IGNORECASE)
CV_FILE_NAME = re.compile(r"cv|resume|résumé|سيرة", re.IGNORECASE)  # "cv1.docx", "Farah_CV.pdf"
# A CV whose name and message do not say so ("fix this" + 01_senior_12_years.txt): known by
# its section headings (two or more different ones, each on its own line)
CV_HEADING = re.compile(r"^\W*(education|(?:work )?experience|internships|skills|summary|profile|objective|about me|"
                        r"projects|languages|certifications|التعليم|الخبرات|المهارات|الملخص|اللغات|المشاريع)\W*$",
                        re.IGNORECASE | re.MULTILINE)
CV_REQUEST = "Rewrite my CV in the right GIU template."  # a training request, for "send my CV as pdf"
# Words that only ask for the conversion itself ("convert it to pdf", "حوله بي دي اف").
CONVERSION_WORDS = re.compile(r"\b(convert|turn|change|save|export|make|send|give|download)\w*|حول\w*|ابعت\w*|نزل\w*",
                              re.IGNORECASE)


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
        buildings=[{"letter": letter, "name": BUILDINGS[letter]} for letter in result.buildings],
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
        wants_edit, wants_pdf = is_edit_request(body.query), is_pdf_request(body.query)
        # "Convert it to pdf" only wants a PDF (no model); "translate it and send it as pdf" also edits.
        only_pdf = wants_pdf and not is_edit_request(CONVERSION_WORDS.sub(" ", body.query))
        wants_edit = wants_edit and not only_pdf
        career = agent_name == "internship_career"
        uploads = sent_files(body)
        if len(uploads) > 1:  # several files: questions about them ("compare these", "summarize them")
            if wants_pdf:
                raise ValueError("To get a file back (a PDF, an edited file or a restructured CV), "
                                 "attach one file at a time.")
            attachment = combine_attachments([read_attachment(f.filename, f.data_base64) for f in uploads])
            return Outcome(AGENTS[agent_name].run(body.query, user_type, history, attachment))
        if uploads:
            upload = uploads[0]
            filename = upload.filename
            extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            is_cv = career and bool(CV_WORDS.search(body.query) or CV_FILE_NAME.search(filename))
            if career and not is_cv and (wants_edit or wants_pdf):
                is_cv = looks_like_cv(read_attachment(filename, upload.data_base64).text)
            if is_cv and (wants_edit or wants_pdf):  # restructure the CV (and send it as PDF + Word)
                attachment = read_attachment(filename, upload.data_base64)
                return restructure_cv(body.query, user_type, history, attachment, filename)
            if extension in EDITABLE_TYPES and wants_edit:
                return edit(body, agent_name, upload=(filename, decode(upload.data_base64)), also_pdf=wants_pdf)
            if extension in EDITABLE_TYPES and wants_pdf:
                return as_pdf(decode(upload.data_base64), filename=filename)
            attachment = read_attachment(filename, upload.data_base64)
            return Outcome(AGENTS[agent_name].run(body.query, user_type, history, attachment))
        info = (storage.current(body.conversation_id)
                if body.document_token and storage.is_latest(body.conversation_id, body.document_token) else None)
        if info and only_pdf:  # "send it as pdf": the open document as a PDF
            return current_as_pdf(body.conversation_id, info)
        if info and wants_edit:
            cv_file_open = career and not info.get("cv") and bool(CV_WORDS.search(body.query) or CV_FILE_NAME.search(info["filename"]))
            if cv_file_open and CV_REWRITE_WORDS.search(body.query):  # "restructure it": the CV model, not the editor
                data, extension = storage.latest_file(body.conversation_id)
                name = info["filename"].rsplit(".", 1)[0] + extension
                attachment = read_attachment(name, base64.b64encode(data).decode())
                return restructure_cv(body.query, user_type, history, attachment, name)
            return edit(body, agent_name, upload=None, also_pdf=wants_pdf)
        return Outcome(AGENTS[agent_name].run(body.query, user_type, history, None))
    except ValueError as error:  # a bad attachment or a broken agent rule
        raise HTTPException(400, str(error))
    except (httpx.HTTPError, LLMError):  # OpenRouter unreachable, an error, or no answer
        raise HTTPException(502, "The assistant is temporarily unavailable. Please try again.")


def sent_files(body: ChatRequest) -> list:
    """The files sent with the message: `attachments`, or the single `attachment`."""
    return body.attachments or ([body.attachment] if body.attachment else [])


def looks_like_cv(text: str | None) -> bool:
    """A CV by its content: at least two different CV section headings (spaced-out headings
    such as "S U M M A R Y" count too)."""
    text = re.sub(r"^\w(?: \w)+$", lambda m: m.group().replace(" ", ""), text or "", flags=re.MULTILINE)
    return len({heading.lower() for heading in CV_HEADING.findall(text)}) >= 2


def decode(data_base64: str) -> bytes:
    try:
        return base64.b64decode(data_base64, validate=True)
    except binascii.Error:
        raise ValueError("The file could not be read. Please try uploading it again.")


def edit(body: ChatRequest, agent_name: str, upload, also_pdf: bool = False) -> Outcome:
    """The document editor's answer: what changed, and the edited file."""
    result, info = edit_conversation_document(body.conversation_id, body.query, upload, body.document_token, agent_name)
    answer = result.summary + "".join(f"\n- {note}" for note in result.notes)
    files = [(result.data, result.extension, None)]
    if upload is None and info.get("cv") and result.extension == ".docx":
        # A restructured CV: its Word version was edited; make a new PDF of it as well.
        stem = info["filename"].rsplit(".", 1)[0]
        files = [(cv_pdf(docx_to_cv_text(result.data)), ".pdf", f"{stem}_restructured.pdf"),
                 (result.data, ".docx", f"{stem}_restructured.docx")]
    elif also_pdf and result.extension != ".pdf":  # "... and send it as pdf"
        stem = info["filename"].rsplit(".", 1)[0]
        files = [(document_pdf(result.extension, result.data), ".pdf", f"{stem}_edited.pdf"),
                 (result.data, result.extension, None)]
    return Outcome(AgentResponse(answer=answer, sources=[]), files=files, changes=result.changes)


def restructure_cv(query: str, user_type: str, history, attachment, filename: str) -> Outcome:
    """The CV model restructures the CV; a restructured CV comes back as PDF + Word files.
    A request that only asks for a PDF ("send my CV as pdf"), or that does not mention a CV or
    a template ("fix this"), is sent as a training-style rewrite request."""
    names_it = CV_WORDS.search(query) or re.search(r"template|student|london|modern", query, re.IGNORECASE)
    question = query if CV_REWRITE_WORDS.search(query) and names_it else CV_REQUEST
    response = AGENTS["internship_career"].run(question, user_type, history, attachment)
    return cv_files(response, filename) if is_restructured_cv(response.answer) else Outcome(response)


def as_pdf(data: bytes, filename: str) -> Outcome:
    """A new upload sent back as a simple PDF (the original is kept for later edits)."""
    extension = check_file(filename, data, config.DOC_EDIT_MAX_MB)
    stem = storage.safe_name(filename).rsplit(".", 1)[0]
    answer = "Here is your document as a PDF." + LAYOUT_NOTE.get(extension, "")
    return Outcome(AgentResponse(answer=answer, sources=[]), new_document=filename, files=[
        (document_pdf(extension, data), ".pdf", f"{stem}.pdf"), (data, extension, storage.safe_name(filename))])


def current_as_pdf(conversation_id: int, info: dict) -> Outcome:
    """The chat's open document as a PDF: a restructured CV in its CV layout, other files
    as a simple PDF. The editable version stays the one later edits change."""
    data, extension = storage.latest_file(conversation_id)
    stem = info["filename"].rsplit(".", 1)[0]
    if info.get("cv") and extension == ".docx":
        pdf, name, answer = cv_pdf(docx_to_cv_text(data)), f"{stem}_restructured.pdf", "Here is your CV as a PDF."
    else:
        pdf, name = document_pdf(extension, data), f"{stem}{'_edited' if info.get('version_number') else ''}.pdf"
        answer = "Here is your document as a PDF." + LAYOUT_NOTE.get(extension, "")
    if extension == ".pdf":
        return Outcome(AgentResponse(answer="This document is already a PDF: use View or Download.", sources=[]),
                       files=[(data, ".pdf", name)])
    keep = info["versions"][-1].get("name")
    return Outcome(AgentResponse(answer=answer, sources=[]), files=[(pdf, ".pdf", name), (data, extension, keep)])


LAYOUT_NOTE = {
    ".docx": " It shows the text, headings, lists and tables; the original Word layout (fonts, columns, pictures) is not kept.",
    ".pptx": " It shows the text of each slide; the slide design is not kept.",
    ".xlsx": " It shows each sheet as a table; formatting and charts are not kept.",
}


def cv_files(response: AgentResponse, filename: str) -> Outcome:
    """The restructured CV as a PDF (to view and download) and a Word file (to change); the
    CV ANALYSIS after it is the chat message (a short note if the model wrote none)."""
    stem = storage.safe_name(filename).rsplit(".", 1)[0]
    cv, analysis = split_cv(response.answer)
    pdf = cv_pdf(cv, one_page=is_one_page_target(analysis))
    if analysis:  # "Your CV is still longer than the target length..." only when the PDF really is
        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            analysis = check_length(analysis, document.page_count)
    message = analysis or ("ده الـ CV بعد الترتيب." if is_arabic(cv) else "Here is your restructured CV.")
    return Outcome(replace(response, answer=message), new_document=f"{stem}.pdf", cv=True, files=[
        (pdf, ".pdf", f"{stem}_restructured.pdf"),
        (cv_docx(cv), ".docx", f"{stem}_restructured.docx"),
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
    names = [f.filename for f in sent_files(body)]
    if names:
        user_message += f"\n[Attached file{'s' if len(names) > 1 else ''}: {', '.join(names)}]"

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
