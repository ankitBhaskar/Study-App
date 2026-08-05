"""Daily per-user usage cap, enforced with a Firestore transaction."""

from __future__ import annotations

from fastapi import HTTPException
from firebase_admin import firestore

from ..config import DAILY_USAGE_LIMIT
from ..firebase_client import get_firestore_client
from ..utils import _today_key


def reserve_usage(uid: str) -> None:
    """Atomically claim one of the day's usage units, or raise 429 if the
    limit is already reached. The read-and-increment runs inside a Firestore
    transaction so concurrent requests can't each slip past a stale read and
    overshoot the cap (the previous check-then-increment pair could).

    A unit is consumed at admission — call this AFTER cache hits and cheap
    validation (so those stay free), but before the paid Gemini/TTS work.
    A request that fails downstream still counts, which also means a failing
    call can't be retry-stormed for free."""
    db = get_firestore_client()
    if db is None:
        return
    usage_ref = db.collection("users").document(uid).collection("usage").document(_today_key())

    @firestore.transactional
    def _claim(transaction) -> None:
        snapshot = usage_ref.get(transaction=transaction)
        current = (snapshot.to_dict() or {}).get("count", 0) if snapshot.exists else 0
        if current >= DAILY_USAGE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"You've used all {DAILY_USAGE_LIMIT} AI actions for today. Please try again tomorrow.",
            )
        transaction.set(usage_ref, {"count": current + 1, "date": _today_key()}, merge=True)

    try:
        # Extra retry headroom so a handful of parallel requests from one user
        # (all contending on this single daily counter) still commit cleanly.
        _claim(db.transaction(max_attempts=15))
    except HTTPException:
        raise
    except ValueError:
        # Transaction couldn't commit under heavy contention even after all
        # retries. It failed closed (no unit granted, so the cap is never
        # exceeded) — surface a retryable 429 rather than a raw 500.
        raise HTTPException(
            status_code=429,
            detail="Too many requests at once. Please try again in a moment.",
        )
