"""Liveness and authenticated deployment/config status endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import require_user
from ..config import (
    ALLOWED_EMAILS,
    APP_NAME,
    DAILY_USAGE_LIMIT,
    ELEVENLABS_MODEL,
    ENABLE_BROWSER_VOICE,
    GEMINI_MODEL,
    GEMINI_TTS_MODEL,
    TTS_PROVIDER,
    get_elevenlabs_api_key,
    get_gemini_api_key,
)
from ..firebase_client import firebase_configured
from ..models import AuthedUser

router = APIRouter()


@router.get("/api/health")
def health() -> dict[str, Any]:
    # Public (pre-auth) endpoint — keep it to liveness plus the one config
    # flag the signed-out frontend genuinely needs (browser_voice_enabled,
    # read before login). The detailed provider/config status that used to
    # live here is free recon for an attacker and now lives behind auth at
    # /api/status.
    return {
        "status": "ok",
        "service": APP_NAME,
        "browser_voice_enabled": ENABLE_BROWSER_VOICE,
    }


@router.get("/api/status")
def status(user: AuthedUser = Depends(require_user)) -> dict[str, Any]:
    """Authenticated deployment/config status (which providers are keyed,
    the active TTS backend, whether access is restricted). Kept off the
    public /api/health so it isn't readable without a valid account."""
    return {
        "service": APP_NAME,
        "gemini_model": GEMINI_MODEL,
        "gemini_key_configured": bool(get_gemini_api_key()),
        "tts_provider": TTS_PROVIDER,
        "gemini_tts_model": GEMINI_TTS_MODEL,
        "elevenlabs_model": ELEVENLABS_MODEL,
        "elevenlabs_key_configured": bool(get_elevenlabs_api_key()),
        "firebase_configured": firebase_configured(),
        "daily_usage_limit": DAILY_USAGE_LIMIT,
        "access_restricted": bool(ALLOWED_EMAILS),
        "browser_voice_enabled": ENABLE_BROWSER_VOICE,
    }
