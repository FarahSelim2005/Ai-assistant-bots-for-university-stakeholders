"""POST /feedback: store a 1-5 rating for an assistant message."""
from fastapi import APIRouter, HTTPException

from app.db import get_connection
from app.schemas import FeedbackRequest, FeedbackResponse

router = APIRouter()


@router.post("/feedback", response_model=FeedbackResponse)
def create_feedback(body: FeedbackRequest) -> FeedbackResponse:
    with get_connection() as conn:
        message = conn.execute(
            "SELECT role FROM messages WHERE id = %s", (body.message_id,)
        ).fetchone()
        if message is None:
            raise HTTPException(404, "Message not found.")
        if message[0] != "assistant":
            raise HTTPException(400, "Only assistant messages can be rated.")

        feedback_id = conn.execute(
            "INSERT INTO feedback (message_id, rating) VALUES (%s, %s) RETURNING id",
            (body.message_id, body.rating),
        ).fetchone()[0]
    return FeedbackResponse(feedback_id=feedback_id)
