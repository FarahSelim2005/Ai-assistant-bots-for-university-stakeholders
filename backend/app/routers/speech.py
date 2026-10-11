"""POST /transcribe: turn a recorded voice question into text (Arabic or English)."""
import base64
import binascii

from fastapi import APIRouter, HTTPException

from app import config
from app.schemas import TranscribeRequest, TranscribeResponse
from app.speech import transcribe

router = APIRouter()

# File extension per recording type, so the speech service knows the format.
EXTENSIONS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}


@router.post("/transcribe", response_model=TranscribeResponse)
def transcribe_audio(body: TranscribeRequest) -> TranscribeResponse:
    try:
        audio = base64.b64decode(body.audio_base64, validate=True)
    except binascii.Error:
        raise HTTPException(400, "The recording could not be read.")
    if len(audio) > config.MAX_AUDIO_MB * 1024 * 1024:
        raise HTTPException(400, f"The recording is larger than {config.MAX_AUDIO_MB} MB.")
    extension = EXTENSIONS.get(body.mime_type.split(";")[0].strip().lower(), "webm")
    try:
        text, language = transcribe(audio, filename=f"question.{extension}")
    except Exception:  # e.g. an empty or damaged recording that cannot be decoded
        raise HTTPException(400, "The recording could not be understood. Please try again.")
    return TranscribeResponse(text=text, language=language)
