"""All settings in one place. Values come from backend/.env (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

# Database
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "giu-bots")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# OpenRouter (used for both embeddings and chat)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Multilingual: matches Arabic questions to the English documents far better than
# openai/text-embedding-3-small. 1024 dimensions. Re-run scripts.ingest after changing.
EMBEDDING_MODEL = "baai/bge-m3"
LABS_MODEL = os.getenv("LABS_MODEL", "")
# Optional backups, tried in order when LABS_MODEL fails. Several can be given,
# separated by commas: LABS_BACKUP_MODEL=model-one,model-two
LABS_BACKUP_MODELS = [m.strip() for m in os.getenv("LABS_BACKUP_MODEL", "").split(",") if m.strip()]
VISION_MODEL = os.getenv("VISION_MODEL", "")  # must accept images; used only when an image is attached
# Optional backups for pictures, tried in order when VISION_MODEL fails (comma-separated,
# all must accept images): VISION_BACKUP_MODEL=model-one,model-two
VISION_BACKUP_MODELS = [m.strip() for m in os.getenv("VISION_BACKUP_MODEL", "").split(",") if m.strip()]

# Local model through Ollama (https://ollama.com). Write "ollama" in a model list to use
# OLLAMA_MODEL, e.g. LABS_BACKUP_MODEL=...,ollama. Free and unlimited, but slow on a laptop.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:1b")  # switch back with OLLAMA_MODEL=gemma4:e4b
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TIMEOUT = 120.0  # seconds
OLLAMA_NUM_PREDICT = 100  # max answer tokens: a laptop writes only a few words per second
OLLAMA_NUM_CTX = 2048  # context window; a small prompt is processed faster
OLLAMA_MAX_CONTEXT_CHARS = 1200  # documents/attachment text sent to the local model (2500 took ~7-9 s)
OLLAMA_HISTORY_MESSAGES = 2  # earlier messages sent to the local model (one question + answer)

# Voice call, speech-to-text 1: Groq's hosted Whisper (fast, best Arabic, free tier).
# Get a key at https://console.groq.com and put GROQ_API_KEY in .env; without a key
# the local Whisper below is used.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"

# Voice call, speech-to-text 2 (fallback): local Whisper (tiny, base, small, medium, large-v3).
# "base" takes ~3.5 s per question on a 4-thread CPU; "small" understands Arabic
# better but takes ~12 s there. Use "small" or larger on a faster machine.
WHISPER_MODEL = "base"
MAX_AUDIO_MB = 10

# Chat attachments
MAX_UPLOAD_MB = 5
MAX_ATTACHMENT_CHARS = 12000  # longer documents are cut to keep answers fast

# API
FRONTEND_ORIGIN = "http://localhost:5173"  # the Vite dev server, allowed by CORS

# Retrieval
TOP_K = 4                    # how many chunks the retriever returns
# Suggest another agent only when it clearly wins: its description must match the
# question at least this much better than the second-best agent (tuned for bge-m3).
AGENT_LINK_MIN_GAP = 0.05
# Hand a question over to another BUILT agent (fallback + link) when that agent clearly
# owns it (gap >= HANDOVER_MIN_GAP) and this agent's best document is only a weak
# match (score < HANDOVER_MAX_SCORE). E.g. "How do I apply for an internship?" asked
# to Labs & Research -> link to the Internship & Career agent.
HANDOVER_MIN_GAP = 0.10
HANDOVER_MAX_SCORE = 0.55
SIMILARITY_THRESHOLD = 0.48  # chunks scoring below this are not used to answer (tuned for bge-m3)

# Ingestion
RAW_DATA_DIR = BACKEND_DIR / "data" / "raw"
CHUNK_SIZE_WORDS = 200
CHUNK_OVERLAP_WORDS = 40
