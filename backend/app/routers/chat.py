"""POST /chat: answer a question in a conversation and store both messages.

If the user presses "Stop" in the browser while the answer is being made, the browser
stops waiting. The answer is then thrown away instead of saved, so a stopped question
does not appear in the conversation history (and does not affect follow-up questions).
"""
from dataclasses import asdict

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.agents import AGENTS
from app.agents.base import AgentResponse
from app.attachments import read_attachment
from app.db import get_connection
from app.llm.client import LLMError
from app.schemas import ChatRequest, ChatResponse

router = APIRouter()

HISTORY_SIZE = 4  # earlier messages sent along so follow-up questions make sense
STOPPED_BY_USER = 499  # non-standard "client closed request" status, never seen by the browser


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request):
    # The work itself is slow, blocking code (database, model calls), so it runs in a
    # worker thread; meanwhile this function can notice when the user pressed "Stop".
    result = await run_in_threadpool(answer_question, body)
    if await request.is_disconnected():
        return Response(status_code=STOPPED_BY_USER)
    message_id = await run_in_threadpool(save_messages, body, result.answer)
    return ChatResponse(
        answer=result.answer,
        sources=result.sources,
        locations=[asdict(location) for location in result.locations],
        places=[{"key": place.key, "name": place.name} for place in result.places],
        redirect=asdict(result.redirect) if result.redirect else None,
        message_id=message_id,
    )


def answer_question(body: ChatRequest) -> AgentResponse:
    """Load the conversation and its recent messages, then let its agent answer."""
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
        attachment = None
        if body.attachment:
            attachment = read_attachment(body.attachment.filename, body.attachment.data_base64)
        return AGENTS[agent_name].run(body.query, user_type, history, attachment)
    except ValueError as error:  # a bad attachment or a broken agent rule
        raise HTTPException(400, str(error))
    except (httpx.HTTPError, LLMError):  # OpenRouter unreachable, an error, or no answer
        raise HTTPException(502, "The assistant is temporarily unavailable. Please try again.")


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
