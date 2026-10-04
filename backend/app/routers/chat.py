"""POST /chat: answer a question in a conversation and store both messages."""
import httpx
from fastapi import APIRouter, HTTPException

from app.agents import AGENTS
from app.db import get_connection
from app.schemas import ChatRequest, ChatResponse

router = APIRouter()

HISTORY_SIZE = 4  # earlier messages sent along so follow-up questions make sense


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
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
        result = AGENTS[agent_name].run(body.query, user_type, history)
    except ValueError as error:  # an agent rule was broken
        raise HTTPException(400, str(error))
    except httpx.HTTPError:  # OpenRouter unreachable or returned an error
        raise HTTPException(502, "The assistant is temporarily unavailable. Please try again.")

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
            (body.conversation_id, body.query),
        )
        message_id = conn.execute(
            "INSERT INTO messages (conversation_id, role, content) "
            "VALUES (%s, 'assistant', %s) RETURNING id",
            (body.conversation_id, result.answer),
        ).fetchone()[0]

    return ChatResponse(answer=result.answer, sources=result.sources, message_id=message_id)
