"""Request and response bodies of the API (validated by pydantic)."""
from typing import Literal

from pydantic import BaseModel, Field


class SessionRequest(BaseModel):
    user_type: Literal["student", "staff"]
    agent: Literal["labs_research", "internship_career", "graduation_advising"] = "labs_research"


class SessionResponse(BaseModel):
    conversation_id: int


class AttachmentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    # File content as base64 text (a 5 MB file is about 7 million characters). The exact
    # size limit is checked in attachments.py; this is only a hard upper bound.
    data_base64: str = Field(min_length=1, max_length=14_000_000)  # files to edit may be 10 MB


class ChatRequest(BaseModel):
    conversation_id: int
    query: str = Field(min_length=1, max_length=1000)
    attachment: AttachmentIn | None = None
    # The random token of the document this chat is editing (from the last file answer):
    # an edit request without a new file then changes that document.
    document_token: str | None = Field(default=None, max_length=64)


class LocationOut(BaseModel):
    room: str           # e.g. "M005"
    building: str       # "A", "M" or "S"
    building_name: str  # e.g. "Main Administration Building"
    floor: int          # 0 = ground floor
    floor_name: str     # e.g. "Ground floor"


class PlaceOut(BaseModel):
    key: str   # e.g. "gym"; the frontend has its GPS position for the walking link
    name: str  # e.g. "Gym"


class AgentLinkOut(BaseModel):
    agent: str  # e.g. "labs_research"
    name: str   # e.g. "Labs & Research Assistant"
    url: str    # e.g. "/?agent=labs_research"


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    locations: list[LocationOut] = []  # rooms mentioned in the answer, shown on a map
    places: list[PlaceOut] = []  # places outside the buildings in the answer, with walking links
    redirect: AgentLinkOut | None = None  # the agent to ask instead, when this one can't answer
    message_id: int  # id of the saved assistant message, used for feedback
    file: "DocumentFileOut | None" = None  # an edited document or a restructured CV, to view and download
    changes: list["ChangeOut"] = []       # a few before/after examples of an edit


class DocumentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    # base64 text of a document to edit (10 MB is about 13.4 million characters); the exact
    # limit (DOC_EDIT_MAX_MB) is checked in app/documents/formats.py.
    data_base64: str = Field(min_length=1, max_length=14_000_000)


class DocumentEditRequest(BaseModel):
    conversation_id: int
    instruction: str = Field(min_length=1, max_length=2000)
    # A new document to edit; without it, the conversation's current document is edited again,
    # and `document_token` (the random token of its latest version) must be sent: only the
    # browser that edited the document knows it, so others cannot edit or read it.
    document: DocumentIn | None = None
    document_token: str | None = Field(default=None, max_length=64)


class DocumentFileOut(BaseModel):
    filename: str       # the uploaded file's name
    download_name: str  # e.g. "report_edited.docx"
    url: str            # "/documents/<conversation>/<random token>": download link
    view_url: str = ""  # the same + "/view": open it in the browser
    version: int        # 1 = first edit
    token: str = ""     # needed for the next edit of this document
    word_url: str | None = None   # a restructured CV also comes as an editable Word file
    word_name: str | None = None


class ChangeOut(BaseModel):
    before: str
    after: str


class DocumentEditResponse(BaseModel):
    answer: str                  # what was changed, and notes (e.g. converted to Word)
    file: DocumentFileOut
    changes: list[ChangeOut] = []  # a few before/after examples
    message_id: int


class TranscribeRequest(BaseModel):
    # Recorded audio (webm/ogg/wav...) as base64 text; the size is checked in the router.
    audio_base64: str = Field(min_length=1, max_length=15_000_000)
    mime_type: str = "audio/webm"  # what the browser recorded, e.g. "audio/webm;codecs=opus"


class TranscribeResponse(BaseModel):
    text: str      # what the user said ("" if nothing was understood)
    language: str  # "ar" or "en"


class FeedbackRequest(BaseModel):
    message_id: int
    rating: int = Field(ge=1, le=5)


class FeedbackResponse(BaseModel):
    feedback_id: int


ChatResponse.model_rebuild()  # it refers to DocumentFileOut and ChangeOut, defined after it
