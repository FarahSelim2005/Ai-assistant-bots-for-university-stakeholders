"""All settings in one place. Values come from backend/.env (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

# Database. The app connects as DB_USER: the giu_app role from migration 003, which only sees
# the current tenant's rows. migrate.py and ingest.py connect as DB_ADMIN_USER, the owner of
# the tables. Without DB_ADMIN_USER both use DB_USER (a setup without giu_app keeps working).
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "giu-bots")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_ADMIN_USER = os.getenv("DB_ADMIN_USER", "") or DB_USER
DB_ADMIN_PASSWORD = os.getenv("DB_ADMIN_PASSWORD", "") or (DB_PASSWORD if DB_ADMIN_USER == DB_USER else "")
# A separate database for the tests that need PostgreSQL: they migrate it themselves (as
# DB_ADMIN_USER) and are skipped when it is not set. Never the real database.
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "")

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
# The Internship & Career agent can use its own model, e.g. the fine-tuned CV model
# CAREER_MODEL=ollama/giu-cv. Empty: the same models as Labs & Research.
CAREER_MODEL = os.getenv("CAREER_MODEL", "") or LABS_MODEL
CAREER_BACKUP_MODELS = ([m.strip() for m in os.getenv("CAREER_BACKUP_MODEL", "").split(",") if m.strip()]
                        or LABS_BACKUP_MODELS)
VISION_MODEL = os.getenv("VISION_MODEL", "")  # must accept images; used only when an image is attached
# Optional backups for pictures, tried in order when VISION_MODEL fails (comma-separated,
# all must accept images): VISION_BACKUP_MODEL=model-one,model-two
VISION_BACKUP_MODELS = [m.strip() for m in os.getenv("VISION_BACKUP_MODEL", "").split(",") if m.strip()]

# Local model through Ollama (https://ollama.com). Write "ollama" in a model list to use
# OLLAMA_MODEL, e.g. LABS_BACKUP_MODEL=...,ollama. Free and unlimited, but slow on a laptop.
# "groq/<name>" in a model list uses Groq with GROQ_API_KEY, e.g. groq/openai/gpt-oss-120b.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:1b")  # switch back with OLLAMA_MODEL=gemma4:e4b
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TIMEOUT = 300.0  # seconds; a full CV rewrite by the local CV model takes 1-3 minutes
OLLAMA_NUM_PREDICT = 100  # max answer tokens: a laptop writes only a few words per second
OLLAMA_NUM_CTX = 2048  # context window; a small prompt is processed faster
# Context window for CV rewrites by the local CV model (giu-cv): the CV rules (~3,000 tokens)
# + a CV + a 1,500-token answer. 6144 (not 8192) so the model fits fully in a 4 GB GPU.
OLLAMA_FULL_NUM_CTX = 6144
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

# Document editor (app/documents): edit an uploaded .docx/.xlsx/.pptx/.pdf/.txt/.md with an
# instruction and download the result. It uses the Labs models unless DOC_EDIT_MODEL is set
# (not the fine-tuned CV model: it was trained only to rewrite CVs).
DOC_EDIT_MODEL = os.getenv("DOC_EDIT_MODEL", "") or LABS_MODEL
DOC_EDIT_BACKUP_MODELS = ([m.strip() for m in os.getenv("DOC_EDIT_BACKUP_MODEL", "").split(",") if m.strip()]
                          or LABS_BACKUP_MODELS)
DOC_EDIT_MAX_MB = 10            # upload limit for documents to edit
DOC_EDIT_MAX_CHARS = 40000      # longer documents must be split (each edit asks the model per batch)
DOC_EDIT_BATCH_CHARS = 6000     # document text sent to the model at once
DOC_EDIT_MAX_TOKENS = 4000      # answer limit per batch (a translated batch is about as long as the batch)
DOC_EDIT_SCAN_PAGES = 5         # pages of a scanned PDF read by the vision model
DOC_EDIT_KEEP_MINUTES = 60      # uploaded and edited files are deleted after this time
EDITS_DIR = BACKEND_DIR / "data" / "edits"  # one folder per conversation; not in git

# Admin page (/admin) and console (/console): per-user logins (the users table, app/auth.py;
# accounts are made with python -m scripts.create_user).
ADMIN_TOKEN_HOURS = 8              # a login lasts this long
ADMIN_MAX_DOCUMENT_CHARS = 500_000  # about 100 pages of text

# API
FRONTEND_ORIGIN = "http://localhost:5173"  # the Vite dev server, allowed by CORS
# APP_ENV=development (set it in .env on your own computer): CORS also allows the Vite server on
# 127.0.0.1 and any *.localhost subdomain (giu.localhost:5173, demo.localhost:5173), and an
# "X-Tenant: <slug>" header may choose the tenant. Anything else, also a missing APP_ENV (a
# server that forgot it): only the host name decides, and only FRONTEND_ORIGIN is allowed.
APP_ENV = os.getenv("APP_ENV", "production")


def is_development() -> bool:
    return APP_ENV == "development"


DEV_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1|[a-z0-9-]+\.localhost):5173$"

# Tenants (universities). GIU's documents stay in data/raw/<agent>/; every other
# tenant's are in data/tenants/<slug>/<agent>/ (not in git).
DEFAULT_TENANT = "giu"

# Retrieval
TOP_K = 4                    # how many chunks the retriever returns
# Suggest another agent only when it clearly wins: its description must match the
# question at least this much better than the second-best agent (tuned for bge-m3).
AGENT_LINK_MIN_GAP = 0.05
# ...and match it at least this well: off-topic questions ("capital of France?", "tell
# me a joke") score 0.25-0.38 against every agent, real ones 0.42 and more.
AGENT_LINK_MIN_SCORE = 0.40
# Hand a question over to another BUILT agent (fallback + link) when that agent clearly
# owns it (gap >= HANDOVER_MIN_GAP) and this agent's best document is only a weak
# match (score < HANDOVER_MAX_SCORE). E.g. "How do I apply for an internship?" asked
# to Labs & Research -> link to the Internship & Career agent.
HANDOVER_MIN_GAP = 0.10
HANDOVER_MAX_SCORE = 0.55
SIMILARITY_THRESHOLD = 0.48  # chunks scoring below this are not used to answer (tuned for bge-m3)

# Ingestion
RAW_DATA_DIR = BACKEND_DIR / "data" / "raw"
TENANTS_DATA_DIR = BACKEND_DIR / "data" / "tenants"
CHUNK_SIZE_WORDS = 200
CHUNK_OVERLAP_WORDS = 40
