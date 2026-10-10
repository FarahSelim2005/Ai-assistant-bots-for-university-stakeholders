"""POST /transcribe: turn a recorded voice question into text (Arabic or English)."""
import base64
import binascii

from fastapi import APIRouter, HTTPException

from app import config
from app.schemas import TranscribeRequest, TranscribeResponse
from app.speech import transcribe

router = APIRouter()


@router.post("/transcribe", response_model=TranscribeResponse)
def transcribe_audio(body: TranscribeRequest) -> TranscribeResponse:
    try:
        audio = base64.b64decode(body.audio_base64, validate=True)
    except binascii.Error:
        raise HTTPException(400, "The recording could not be read.")
    if len(audio) > config.MAX_AUDIO_MB * 1024 * 1024:
        raise HTTPException(400, f"The recording is larger than {config.MAX_AUDIO_MB} MB.")
    try:
        text, language = transcribe(audio)
    except Exception:  # e.g. an empty or damaged recording that cannot be decoded
        raise HTTPException(400, "The recording could not be understood. Please try again.")
    return TranscribeResponse(text=text, language=language)
