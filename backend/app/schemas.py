"""Request and response bodies of the API (validated by pydantic)."""
from typing import Literal

from pydantic import BaseModel, Field


class SessionRequest(BaseModel):
    user_type: Literal["student", "staff"]
    agent: Literal["labs_research"] = "labs_research"


class SessionResponse(BaseModel):
    conversation_id: int


class ChatRequest(BaseModel):
    conversation_id: int
    query: str = Field(min_length=1, max_length=1000)


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    message_id: int  # id of the saved assistant message, used for feedback


class FeedbackRequest(BaseModel):
    message_id: int
    rating: int = Field(ge=1, le=5)


class FeedbackResponse(BaseModel):
    feedback_id: int
