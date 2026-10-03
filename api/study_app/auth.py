"""The require_user FastAPI dependency: verifies a Firebase ID token and
enforces the optional ALLOWED_EMAILS allowlist."""

from __future__ import annotations

from fastapi import Header, HTTPException
from firebase_admin import auth as firebase_auth

from .config import ALLOWED_EMAILS
from .firebase_client import firebase_configured, get_firebase_app
from .models import AuthedUser


async def require_user(authorization: str | None = Header(default=None)) -> AuthedUser:
    if not firebase_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Login is not configured yet. Add FIREBASE_PROJECT_ID, FIREBASE_CLIENT_EMAIL and "
                "FIREBASE_PRIVATE_KEY in your Vercel project settings and redeploy."
            ),
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in required.")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        decoded = firebase_auth.verify_id_token(token, app=get_firebase_app())
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.") from exc

    email = decoded.get("email")
    if ALLOWED_EMAILS and (not email or email.lower() not in ALLOWED_EMAILS):
        raise HTTPException(status_code=403, detail="This app is invite-only. Contact the owner for access.")

    return AuthedUser(uid=decoded["uid"], email=email)
