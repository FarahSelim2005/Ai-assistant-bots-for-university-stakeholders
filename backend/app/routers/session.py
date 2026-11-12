"""POST /session: start a new conversation with one of this university's assistants, for a
student or staff member."""
from fastapi import APIRouter, HTTPException

from app import tenants
from app.agents import find_agent
from app.db import get_connection
from app.schemas import SessionRequest, SessionResponse

router = APIRouter()


@router.post("/session", response_model=SessionResponse)
def create_session(body: SessionRequest) -> SessionResponse:
    tenant_id = tenants.current_id()
    agent = find_agent(tenant_id, body.agent)
    if agent is None or not agent.live:  # also another university's assistant
        raise HTTPException(404, "This assistant does not exist.")
    if body.user_type not in {audience["key"] for audience in tenants.current().audiences}:
        raise HTTPException(400, "Choose who you are first.")
    if body.user_type not in agent.allowed_user_types:
        raise HTTPException(403, f"This assistant is not available for {body.user_type} users.")
    with get_connection(tenant_id) as conn:
        conversation_id = conn.execute(
            "INSERT INTO conversations (tenant_id, agent_id, user_type) VALUES (%s, %s, %s) RETURNING id",
            (tenant_id, agent.id, body.user_type),
        ).fetchone()[0]
    return SessionResponse(conversation_id=conversation_id)
