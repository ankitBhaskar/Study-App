"""User profile and feedback submission endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user
from ..config import DAILY_USAGE_LIMIT
from ..firebase_client import get_firestore_client
from ..models import AuthedUser, FeedbackRequest, FeedbackResponse, ProfileResponse
from ..notifications import send_feedback_email
from ..utils import _today_key

router = APIRouter()


@router.get("/api/profile", response_model=ProfileResponse)
async def get_profile(user: AuthedUser = Depends(require_user)) -> ProfileResponse:
    db = get_firestore_client()
    profile_ref = db.collection("users").document(user.uid)
    snapshot = profile_ref.get()
    if snapshot.exists:
        data = snapshot.to_dict() or {}
    else:
        data = {"email": user.email, "created_at": datetime.now(timezone.utc).isoformat()}
        profile_ref.set(data, merge=True)

    usage_snapshot = profile_ref.collection("usage").document(_today_key()).get()
    usage_today = (usage_snapshot.to_dict() or {}).get("count", 0) if usage_snapshot.exists else 0

    return ProfileResponse(
        uid=user.uid,
        email=data.get("email") or user.email,
        created_at=data.get("created_at", ""),
        usage_today=usage_today,
        daily_limit=DAILY_USAGE_LIMIT,
    )


@router.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest, user: AuthedUser = Depends(require_user)) -> FeedbackResponse:
    if request.rating < 1 or request.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5.")
    comment = request.comment.strip()[:2000]
    context = request.context.strip()[:100]

    db = get_firestore_client()
    if db is not None:
        db.collection("feedback").add(
            {
                "uid": user.uid,
                "email": user.email,
                "rating": request.rating,
                "comment": comment,
                "context": context,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    emailed = await send_feedback_email(request.rating, comment, context, user.email)
    return FeedbackResponse(ok=True, emailed=emailed)
