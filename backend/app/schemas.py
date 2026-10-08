"""Request and response bodies of the API (validated by pydantic)."""
from typing import Literal

from pydantic import BaseModel, Field


class SessionRequest(BaseModel):
    user_type: Literal["student", "staff"]
    agent: Literal["labs_research"] = "labs_research"


class SessionResponse(BaseModel):
    conversation_id: int


class AttachmentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    # File content as base64 text (a 5 MB file is about 7 million characters). The exact
    # size limit is checked in attachments.py; this is only a hard upper bound.
    data_base64: str = Field(min_length=1, max_length=10_000_000)


class ChatRequest(BaseModel):
    conversation_id: int
    query: str = Field(min_length=1, max_length=1000)
    attachment: AttachmentIn | None = None


class LocationOut(BaseModel):
    room: str           # e.g. "M005"
    building: str       # "A", "M" or "S"
    building_name: str  # e.g. "Main Administration Building"
    floor: int          # 0 = ground floor
    floor_name: str     # e.g. "Ground floor"


class AgentLinkOut(BaseModel):
    agent: str  # e.g. "orientation"
    name: str   # e.g. "Orientation Assistant"
    url: str    # e.g. "/?agent=orientation"


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    locations: list[LocationOut] = []  # rooms mentioned in the answer, shown on a map
    redirect: AgentLinkOut | None = None  # the agent to ask instead, when this one can't answer
    message_id: int  # id of the saved assistant message, used for feedback


class FeedbackRequest(BaseModel):
    message_id: int
    rating: int = Field(ge=1, le=5)


class FeedbackResponse(BaseModel):
    feedback_id: int
