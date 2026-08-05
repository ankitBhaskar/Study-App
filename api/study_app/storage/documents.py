"""Shared helpers for loading/validating/deleting a saved document."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..config import MAX_GEMINI_CONTEXT_CHARS
from ..firebase_client import get_firestore_client


def _get_document_or_404(uid: str, doc_id: str):
    db = get_firestore_client()
    doc_ref = db.collection("users").document(uid).collection("documents").document(doc_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc_ref, snapshot.to_dict() or {}


def _require_document_context(data: dict[str, Any], what: str) -> str:
    context = (data.get("document_context") or "").strip()[:MAX_GEMINI_CONTEXT_CHARS]
    if not context:
        raise HTTPException(
            status_code=400,
            detail=f"This document's text wasn't saved, so a new {what} can't be generated. Re-upload the PDF.",
        )
    return context


def _delete_document_and_subcollections(doc_ref) -> None:
    # Firestore doesn't cascade-delete subcollections, so cached audio,
    # saved tutor chat and quiz-attempt history would otherwise be orphaned
    # (unreachable but still stored).
    for audio_doc in doc_ref.collection("audio").stream():
        audio_doc.reference.delete()
    for chat_doc in doc_ref.collection("chat").stream():
        chat_doc.reference.delete()
    for attempt_doc in doc_ref.collection("quiz_attempts").stream():
        attempt_doc.reference.delete()
    for set_doc in doc_ref.collection("flashcard_sets").stream():
        set_doc.reference.delete()
    doc_ref.delete()


def _guess_podcast_style(podcast_data: dict[str, Any]) -> str:
    # Documents saved before style versioning don't record which style their
    # script is in; host count is the best available signal (solo scripts
    # have one host, conversation/interview have two — default conversation).
    return "solo" if len(podcast_data.get("hosts") or []) <= 1 else "conversation"
