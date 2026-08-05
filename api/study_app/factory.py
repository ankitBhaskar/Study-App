"""Builds the FastAPI application: middleware plus every route module."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import APP_NAME
from .routes import chat, documents, flashcards, health, pdf_routes, podcast, profile, quiz, summary

app = FastAPI(
    title=APP_NAME,
    version="0.2.0",
    description="Extracts PDF text and generates study content (summary, quiz, podcast script, tutor chat) with Gemini.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (health, profile, documents, pdf_routes, chat, quiz, flashcards, summary, podcast):
    app.include_router(module.router)
