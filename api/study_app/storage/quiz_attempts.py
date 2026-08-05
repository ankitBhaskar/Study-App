"""Per-document quiz attempt history."""

from __future__ import annotations

from datetime import datetime, timezone

from firebase_admin import firestore

from ..config import MAX_QUIZ_ATTEMPTS
from ..firebase_client import get_firestore_client
from ..models import QuizAttempt, QuizQuestion


def _quiz_attempts_ref(db, uid: str, doc_id: str):
    return (
        db.collection("users")
        .document(uid)
        .collection("documents")
        .document(doc_id)
        .collection("quiz_attempts")
    )


def save_quiz_attempt(uid: str, doc_id: str, questions: list[QuizQuestion], answers: list[int]) -> QuizAttempt:
    # Score is derived here from each question's own correct-answer index,
    # never trusted from the caller.
    score = sum(1 for q, a in zip(questions, answers) if a == q.answer)
    created_at = datetime.now(timezone.utc).isoformat()

    db = get_firestore_client()
    if db is None:
        return QuizAttempt(id="", questions=questions, answers=answers, score=score, total=len(questions), created_at=created_at)

    attempts_ref = _quiz_attempts_ref(db, uid, doc_id)
    _, doc_ref = attempts_ref.add(
        {
            "questions": [q.model_dump() for q in questions],
            "answers": answers,
            "score": score,
            "total": len(questions),
            "created_at": created_at,
        }
    )
    # Bound the history the same way the chat log is bounded, just as
    # separate documents instead of a single truncated array: keep only the
    # most recent MAX_QUIZ_ATTEMPTS attempts.
    stale = list(
        attempts_ref.order_by("created_at", direction=firestore.Query.DESCENDING)
        .offset(MAX_QUIZ_ATTEMPTS)
        .stream()
    )
    for extra in stale:
        extra.reference.delete()

    return QuizAttempt(
        id=doc_ref.id, questions=questions, answers=answers, score=score, total=len(questions), created_at=created_at
    )


def list_quiz_attempts(uid: str, doc_id: str) -> list[QuizAttempt]:
    db = get_firestore_client()
    if db is None:
        return []
    query = (
        _quiz_attempts_ref(db, uid, doc_id)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(MAX_QUIZ_ATTEMPTS)
    )
    attempts = []
    for snapshot in query.stream():
        data = snapshot.to_dict() or {}
        attempts.append(
            QuizAttempt(
                id=snapshot.id,
                questions=[QuizQuestion(**q) for q in data.get("questions", [])],
                answers=data.get("answers", []),
                score=data.get("score", 0),
                total=data.get("total", 0),
                created_at=data.get("created_at", ""),
            )
        )
    return attempts
