"""Document history: list, fetch, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore

from ..auth import require_user
from ..firebase_client import get_firestore_client
from ..models import AuthedUser, DocumentDetail, DocumentListResponse, DocumentRecord, Podcast, QuizQuestion
from ..storage.documents import _delete_document_and_subcollections, _guess_podcast_style

router = APIRouter()


@router.get("/api/documents", response_model=DocumentListResponse)
async def list_documents(user: AuthedUser = Depends(require_user)) -> DocumentListResponse:
    db = get_firestore_client()
    docs_ref = (
        db.collection("users")
        .document(user.uid)
        .collection("documents")
        # Field mask keeps the potentially-large document_context out of the
        # list query; it's fetched per-document via GET /api/documents/{id}.
        .select(["title", "file_name", "file_names", "created_at", "summary", "quiz", "podcast"])
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(50)
    )
    records = []
    for doc in docs_ref.stream():
        data = doc.to_dict() or {}
        records.append(
            DocumentRecord(
                id=doc.id,
                title=data.get("title", "Untitled"),
                file_name=data.get("file_name", ""),
                file_names=data.get("file_names", []),
                created_at=data.get("created_at", ""),
                summary=data.get("summary", []),
                quiz=[QuizQuestion(**q) for q in data.get("quiz", [])],
                podcast=Podcast(**data.get("podcast", {"duration": "0:00", "hosts": [], "transcript": []})),
            )
        )
    return DocumentListResponse(documents=records)


@router.get("/api/documents/{doc_id}", response_model=DocumentDetail)
async def get_document(doc_id: str, user: AuthedUser = Depends(require_user)) -> DocumentDetail:
    db = get_firestore_client()
    snapshot = db.collection("users").document(user.uid).collection("documents").document(doc_id).get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Document not found.")
    data = snapshot.to_dict() or {}
    return DocumentDetail(
        id=snapshot.id,
        title=data.get("title", "Untitled"),
        file_name=data.get("file_name", ""),
        file_names=data.get("file_names", []),
        created_at=data.get("created_at", ""),
        summary=data.get("summary", []),
        quiz=[QuizQuestion(**q) for q in data.get("quiz", [])],
        podcast=Podcast(**data.get("podcast", {"duration": "0:00", "hosts": [], "transcript": []})),
        document_context=data.get("document_context", ""),
        podcast_style=data.get("podcast_style") or _guess_podcast_style(data.get("podcast") or {}),
        saved_styles=sorted((data.get("podcast_versions") or {}).keys()),
    )


@router.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, user: AuthedUser = Depends(require_user)) -> dict[str, str]:
    db = get_firestore_client()
    _delete_document_and_subcollections(
        db.collection("users").document(user.uid).collection("documents").document(doc_id)
    )
    return {"status": "deleted"}


@router.delete("/api/documents")
async def clear_documents(user: AuthedUser = Depends(require_user)) -> dict[str, str]:
    db = get_firestore_client()
    docs_ref = db.collection("users").document(user.uid).collection("documents")
    for doc in docs_ref.stream():
        _delete_document_and_subcollections(doc.reference)
    return {"status": "cleared"}
