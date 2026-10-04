"""POST /session: start a new conversation for a student or staff member."""
from fastapi import APIRouter

from app.db import get_connection
from app.schemas import SessionRequest, SessionResponse

router = APIRouter()


@router.post("/session", response_model=SessionResponse)
def create_session(body: SessionRequest) -> SessionResponse:
    with get_connection() as conn:
        conversation_id = conn.execute(
            "INSERT INTO conversations (user_type, agent) VALUES (%s, %s) RETURNING id",
            (body.user_type, body.agent),
        ).fetchone()[0]
    return SessionResponse(conversation_id=conversation_id)
