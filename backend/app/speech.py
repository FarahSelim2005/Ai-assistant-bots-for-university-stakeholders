"""Speech to text for the voice call. Detects Arabic or English by itself.

1. Groq (if GROQ_API_KEY is set): Whisper large-v3-turbo in the cloud. Fast (under a
   second) and the most accurate for Arabic; free tier of about 2,000 requests a day.
2. Local Whisper (faster-whisper) as the fallback when Groq has no key, is unreachable
   or over its limit. Free and offline, but slower and weaker in Arabic on a laptop.
"""
import io
import threading

import httpx
from faster_whisper import WhisperModel

from app import config

LANGUAGES = ("ar", "en")  # the only languages the call should produce
# Showing Whisper a mixed example helps it keep English words in Latin letters
# inside Arabic sentences (e.g. "الـ AI lab") instead of transliterating them.
MIXED_PROMPT = "فين الـ AI lab؟ Where is the Admission Office? مكتب شئون الطلاب في Building S, room S201."
# Groq reports the language as a name; the rest of the app uses ISO codes.
LANGUAGE_CODES = {"arabic": "ar", "english": "en"}

_groq = httpx.Client(base_url=config.GROQ_BASE_URL, timeout=20.0)
_model: WhisperModel | None = None
_lock = threading.Lock()


def transcribe(audio: bytes, filename: str = "question.webm") -> tuple[str, str]:
    """Turn recorded speech into (text, language code). Tries Groq, then local Whisper."""
    if config.GROQ_API_KEY:
        try:
            return transcribe_with_groq(audio, filename)
        except (httpx.HTTPError, KeyError, ValueError):
            pass  # no internet, limit reached, unexpected reply... use local Whisper
    return transcribe_locally(audio)


def transcribe_with_groq(audio: bytes, filename: str, language: str | None = None) -> tuple[str, str]:
    data = {"model": config.GROQ_WHISPER_MODEL, "response_format": "verbose_json",
            "prompt": MIXED_PROMPT, "temperature": "0"}
    if language:
        data["language"] = language
    response = _groq.post(
        "/audio/transcriptions",
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
        data=data,
        files={"file": (filename, audio)},
    )
    response.raise_for_status()
    result = response.json()
    detected = LANGUAGE_CODES.get(str(result.get("language", "")).lower(), result.get("language"))
    if detected not in LANGUAGES and not language:
        # Whisper guessed another language (short or noisy clip): Egyptian students
        # mostly speak Arabic, so try again as Arabic.
        return transcribe_with_groq(audio, filename, language="ar")
    return result["text"].strip(), language or detected


def get_model() -> WhisperModel:
    """Load the local Whisper model the first time it is needed (takes a few seconds)."""
    global _model
    with _lock:
        if _model is None:
            _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe_locally(audio: bytes) -> tuple[str, str]:
    """Local Whisper on the CPU (works offline)."""
    model = get_model()
    segments, info = model.transcribe(
        io.BytesIO(audio), beam_size=5, vad_filter=True, initial_prompt=MIXED_PROMPT,
    )
    language = info.language
    if language not in LANGUAGES:
        # Whisper guessed another language (e.g. on a short or noisy clip):
        # transcribe again with whichever of Arabic/English it found more likely.
        probabilities = dict(info.all_language_probs or [])
        language = max(LANGUAGES, key=lambda code: probabilities.get(code, 0.0))
        segments, info = model.transcribe(
            io.BytesIO(audio), language=language, beam_size=5, vad_filter=True,
            initial_prompt=MIXED_PROMPT,
        )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text, language
