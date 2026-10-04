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
EMBEDDING_MODEL = "openai/text-embedding-3-small"  # 1536 dimensions
LABS_MODEL = os.getenv("LABS_MODEL", "")

# API
FRONTEND_ORIGIN = "http://localhost:5173"  # the Vite dev server, allowed by CORS

# Retrieval
TOP_K = 4                    # how many chunks the retriever returns
SIMILARITY_THRESHOLD = 0.35  # chunks scoring below this are not used to answer

# Ingestion
RAW_DATA_DIR = BACKEND_DIR / "data" / "raw"
CHUNK_SIZE_WORDS = 200
CHUNK_OVERLAP_WORDS = 40
