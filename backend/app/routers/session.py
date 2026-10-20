"""POST /session: start a new conversation with an agent for a student or staff member."""
from fastapi import APIRouter, HTTPException

from app.agents import AGENTS
from app.db import get_connection
from app.schemas import SessionRequest, SessionResponse

router = APIRouter()


@router.post("/session", response_model=SessionResponse)
def create_session(body: SessionRequest) -> SessionResponse:
    if body.user_type not in AGENTS[body.agent].allowed_user_types:
        raise HTTPException(403, f"This assistant is not available for {body.user_type} users.")
    with get_connection() as conn:
        conversation_id = conn.execute(
            "INSERT INTO conversations (user_type, agent) VALUES (%s, %s) RETURNING id",
            (body.user_type, body.agent),
        ).fetchone()[0]
    return SessionResponse(conversation_id=conversation_id)
