"""Speech to text for the voice call, with Whisper running locally (faster-whisper).

Whisper detects the spoken language by itself, so the user can speak Arabic, English
or a mix without choosing a language. Runs on the CPU, needs no API key and uses no
OpenRouter requests. The model is downloaded once (to the Hugging Face cache) and
loaded once per backend process.
"""
import io
import threading

from faster_whisper import WhisperModel

from app import config

LANGUAGES = ("ar", "en")  # the only languages the call should produce
# Showing Whisper a mixed example helps it keep English words in Latin letters
# inside Arabic sentences (e.g. "الـ AI lab") instead of transliterating them.
MIXED_PROMPT = "فين الـ AI lab؟ Where is the Admission Office? مكتب شئون الطلاب في Building S, room S201."

_model: WhisperModel | None = None
_lock = threading.Lock()


def get_model() -> WhisperModel:
    """Load the Whisper model the first time it is needed (takes a few seconds)."""
    global _model
    with _lock:
        if _model is None:
            _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe(audio: bytes) -> tuple[str, str]:
    """Turn recorded speech (webm, ogg, wav, mp3...) into (text, language code)."""
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
