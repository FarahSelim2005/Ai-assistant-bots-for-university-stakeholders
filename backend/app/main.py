"""FastAPI application: creates the app, enables CORS and registers the routers.

Run from the backend folder:
    uvicorn app.main:app --reload
Interactive docs: http://localhost:8000/docs
"""
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.llm.client import warm_up_ollama
from app.documents.storage import remove_old_files
from app.routers import admin, chat, console, documents, feedback, session, speech, tenant
from app.speech import get_model
from app.tenants import TenantMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the Whisper model in the background at start-up, so the first voice
    # question does not have to wait for it (the first run also downloads it).
    threading.Thread(target=get_model, daemon=True).start()
    remove_old_files()  # documents left from editing before the restart
    # Same for the local Ollama model, if one of the configured models uses it.
    if any(m == "ollama" or m.startswith("ollama/") for m in [config.LABS_MODEL, *config.LABS_BACKUP_MODELS]):
        threading.Thread(target=warm_up_ollama, daemon=True).start()
    yield


def cors_options(app_env: str) -> dict:
    """Which browser origins may call the API: the Vite dev server on localhost, and in
    development also on 127.0.0.1 and any *.localhost subdomain (one per university)."""
    return {"allow_origins": [config.FRONTEND_ORIGIN],
            "allow_origin_regex": config.DEV_ORIGIN_REGEX if app_env == "development" else None,
            "allow_methods": ["*"], "allow_headers": ["*"]}


app = FastAPI(title="University assistants", lifespan=lifespan)

# Every request gets its tenant from the host name (tenants.py). Added first, so CORS
# (added after it) runs outside it: preflight requests need no tenant, and a "404 unknown
# university" still carries the CORS headers the browser needs to show it.
app.add_middleware(TenantMiddleware)
app.add_middleware(CORSMiddleware, **cors_options(config.APP_ENV))

app.include_router(tenant.router)
app.include_router(session.router)
app.include_router(chat.router)
app.include_router(feedback.router)
app.include_router(speech.router)
app.include_router(documents.router)
app.include_router(admin.router)
app.include_router(console.router)
