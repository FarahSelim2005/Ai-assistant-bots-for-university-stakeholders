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
from app.routers import chat, feedback, session, speech
from app.speech import get_model


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the Whisper model in the background at start-up, so the first voice
    # question does not have to wait for it (the first run also downloads it).
    threading.Thread(target=get_model, daemon=True).start()
    # Same for the local Ollama model, if one of the configured models uses it.
    if any(m == "ollama" or m.startswith("ollama/") for m in [config.LABS_MODEL, *config.LABS_BACKUP_MODELS]):
        threading.Thread(target=warm_up_ollama, daemon=True).start()
    yield


app = FastAPI(title="GIU Labs & Research Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session.router)
app.include_router(chat.router)
app.include_router(feedback.router)
app.include_router(speech.router)
