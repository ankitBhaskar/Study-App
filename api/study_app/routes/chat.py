"""Tutor chat: one-off Q&A over a document plus its saved transcript log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user
from ..config import (
    MAX_CHAT_QUESTION_CHARS,
    MAX_CHAT_TURN_CHARS,
    MAX_GEMINI_CONTEXT_CHARS,
    MAX_STORED_CHAT_MESSAGES,
    MAX_STORED_CHAT_TEXT_BYTES,
)
from ..firebase_client import get_firestore_client
from ..gemini_client import call_gemini
from ..models import AuthedUser, ChatLogRequest, ChatLogResponse, ChatMessage, ChatRequest, ChatResponse
from ..prompt_safety import frame_untrusted_document, sanitize_label
from ..storage.usage import reserve_usage
from ..utils import truncate_utf8

router = APIRouter()


def _chat_log_ref(db, uid: str, doc_id: str):
    return (
        db.collection("users")
        .document(uid)
        .collection("documents")
        .document(doc_id)
        .collection("chat")
        .document("log")
    )


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: AuthedUser = Depends(require_user)) -> ChatResponse:
    reserve_usage(user.uid)

    context = request.document_context.strip()[:MAX_GEMINI_CONTEXT_CHARS]
    if not context:
        raise HTTPException(status_code=400, detail="Document context is missing. Please upload the PDF again.")

    question = request.question.strip()[:MAX_CHAT_QUESTION_CHARS]
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    # file_name is client-supplied free text (it round-trips through the
    # browser with every chat call) and context may itself contain text
    # pulled from an adversarial document — neither is trustworthy input to
    # a systemInstruction, so both get the same hardening applied at upload
    # time (see pdf_processing.read_uploads / prompt_safety.py).
    file_name = sanitize_label(request.file_name, 200) or "uploaded-document.pdf"
    system_instruction = (
        "You are a friendly study tutor. Answer questions using ONLY the uploaded document below. "
        "If a question cannot be answered from the document, reply: "
        "'Please ask a question related to the uploaded PDF.' Keep answers concise and clear.\n\n"
        f"File name: {file_name}\n\n"
        f"{frame_untrusted_document(context)}"
    )

    # History only ever lands in user/model content turns, never in the
    # systemInstruction, whatever role the client claims for it.
    contents: list[dict[str, Any]] = []
    for turn in request.history[-20:]:
        role = "user" if turn.role == "user" else "model"
        text = turn.text.strip()[:MAX_CHAT_TURN_CHARS]
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": question}]})

    answer = await call_gemini(system_instruction, contents, json_response=False)
    return ChatResponse(answer=answer.strip())


@router.get("/api/documents/{doc_id}/chat", response_model=ChatLogResponse)
async def get_chat_log(doc_id: str, user: AuthedUser = Depends(require_user)) -> ChatLogResponse:
    # Returns the saved tutor conversation for this document so it can be
    # restored on the next visit. Empty when nothing has been saved yet.
    db = get_firestore_client()
    if db is None:
        return ChatLogResponse(messages=[])
    snapshot = _chat_log_ref(db, user.uid, doc_id).get()
    if not snapshot.exists:
        return ChatLogResponse(messages=[])
    data = snapshot.to_dict() or {}
    return ChatLogResponse(messages=[ChatMessage(**m) for m in data.get("messages", [])])


@router.put("/api/documents/{doc_id}/chat", response_model=ChatLogResponse)
async def save_chat_log(
    doc_id: str, request: ChatLogRequest, user: AuthedUser = Depends(require_user)
) -> ChatLogResponse:
    # Persisting chat is storage only — no paid API call, so it doesn't touch
    # the usage limit. Keep only the most recent messages, each text bounded,
    # so the stored transcript stays well under Firestore's 1 MiB cap.
    messages = [
        ChatMessage(role=m.role, text=truncate_utf8(m.text, MAX_STORED_CHAT_TEXT_BYTES))
        for m in request.messages[-MAX_STORED_CHAT_MESSAGES:]
    ]
    db = get_firestore_client()
    if db is not None:
        _chat_log_ref(db, user.uid, doc_id).set({"messages": [m.model_dump() for m in messages]})
    return ChatLogResponse(messages=messages)
