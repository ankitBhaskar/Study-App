"""Per-document flashcard set history — every generated set is kept."""

from __future__ import annotations

from datetime import datetime, timezone

from firebase_admin import firestore

from ..config import MAX_FLASHCARD_SETS
from ..firebase_client import get_firestore_client
from ..models import Flashcard, FlashcardSet


def _flashcard_sets_ref(db, uid: str, doc_id: str):
    return (
        db.collection("users")
        .document(uid)
        .collection("documents")
        .document(doc_id)
        .collection("flashcard_sets")
    )


def save_flashcard_set(uid: str, doc_id: str, cards: list[Flashcard]) -> FlashcardSet:
    created_at = datetime.now(timezone.utc).isoformat()
    db = get_firestore_client()
    if db is None:
        return FlashcardSet(id="", cards=cards, created_at=created_at)

    sets_ref = _flashcard_sets_ref(db, uid, doc_id)
    _, doc_ref = sets_ref.add(
        {"cards": [c.model_dump() for c in cards], "created_at": created_at}
    )
    # Old sets are kept (that's the point — generating a new set never loses
    # the previous ones), just bounded like quiz attempts are.
    stale = list(
        sets_ref.order_by("created_at", direction=firestore.Query.DESCENDING)
        .offset(MAX_FLASHCARD_SETS)
        .stream()
    )
    for extra in stale:
        extra.reference.delete()
    return FlashcardSet(id=doc_ref.id, cards=cards, created_at=created_at)


def list_flashcard_sets(uid: str, doc_id: str) -> list[FlashcardSet]:
    db = get_firestore_client()
    if db is None:
        return []
    query = (
        _flashcard_sets_ref(db, uid, doc_id)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(MAX_FLASHCARD_SETS)
    )
    sets = []
    for snapshot in query.stream():
        data = snapshot.to_dict() or {}
        sets.append(
            FlashcardSet(
                id=snapshot.id,
                cards=[Flashcard(**c) for c in data.get("cards", [])],
                created_at=data.get("created_at", ""),
            )
        )
    return sets
