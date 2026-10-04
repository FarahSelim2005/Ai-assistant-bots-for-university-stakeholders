"""FastAPI application: creates the app, enables CORS and registers the routers.

Run from the backend folder:
    uvicorn app.main:app --reload
Interactive docs: http://localhost:8000/docs
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.routers import chat, feedback, session

app = FastAPI(title="GIU Labs & Research Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session.router)
app.include_router(chat.router)
app.include_router(feedback.router)
