"""POST /feedback: store a 1-5 rating for an assistant message."""
from fastapi import APIRouter, HTTPException

from app import tenants
from app.db import get_connection
from app.schemas import FeedbackRequest, FeedbackResponse

router = APIRouter()


@router.post("/feedback", response_model=FeedbackResponse)
def create_feedback(body: FeedbackRequest) -> FeedbackResponse:
    tenant_id = tenants.current_id()
    with get_connection(tenant_id) as conn:
        message = conn.execute(
            "SELECT role FROM messages WHERE id = %s AND tenant_id = %s", (body.message_id, tenant_id)
        ).fetchone()
        if message is None:  # also another university's message
            raise HTTPException(404, "Message not found.")
        if message[0] != "assistant":
            raise HTTPException(400, "Only assistant messages can be rated.")

        feedback_id = conn.execute(
            "INSERT INTO feedback (tenant_id, message_id, rating) VALUES (%s, %s, %s) RETURNING id",
            (tenant_id, body.message_id, body.rating),
        ).fetchone()[0]
    return FeedbackResponse(feedback_id=feedback_id)
