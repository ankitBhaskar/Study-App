"""ElevenLabs text-to-speech provider (opt-in via TTS_PROVIDER=elevenlabs)."""

from __future__ import annotations

import httpx
from fastapi import HTTPException

from ..config import (
    ELEVENLABS_API_BASE,
    ELEVENLABS_MODEL,
    ELEVENLABS_TIMEOUT_SECONDS,
    ELEVENLABS_VOICE_HOST_A,
    ELEVENLABS_VOICE_HOST_B,
    get_elevenlabs_api_key,
)
from ..utils import _log_upstream

_cached_voice_ids: tuple[str, str] | None = None


async def resolve_voice_ids(api_key: str) -> tuple[str, str]:
    global _cached_voice_ids

    if ELEVENLABS_VOICE_HOST_A and ELEVENLABS_VOICE_HOST_B:
        return ELEVENLABS_VOICE_HOST_A, ELEVENLABS_VOICE_HOST_B
    if _cached_voice_ids:
        return _cached_voice_ids

    async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT_SECONDS) as client:
        try:
            response = await client.get(f"{ELEVENLABS_API_BASE}/voices", headers={"xi-api-key": api_key})
        except httpx.HTTPError as exc:
            _log_upstream("elevenlabs voices connection", exc)
            raise HTTPException(status_code=502, detail="Could not reach the ElevenLabs service. Please try again.") from exc

    if response.status_code != 200:
        _log_upstream("elevenlabs voices", f"{response.status_code} {response.text[:500]}")
        raise HTTPException(status_code=502, detail="Could not load ElevenLabs voices. Please try again.")

    voices = response.json().get("voices") or []
    if len(voices) < 2:
        raise HTTPException(
            status_code=502,
            detail=(
                "Your ElevenLabs account has fewer than two voices available via the API. "
                "Add voices in the ElevenLabs dashboard (Voice Library → Add to my voices), "
                "or set ELEVENLABS_VOICE_HOST_A/ELEVENLABS_VOICE_HOST_B to specific voice IDs you own."
            ),
        )

    _cached_voice_ids = (voices[0]["voice_id"], voices[1]["voice_id"])
    return _cached_voice_ids


async def elevenlabs_tts(text: str, speaker: int) -> tuple[bytes, str]:
    """Generate one segment via ElevenLabs. Returns (mp3_bytes, mime)."""
    api_key = get_elevenlabs_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "ElevenLabs API key is not configured. Add ELEVENLABS_API_KEY in your Vercel project settings "
                "(Settings → Environment Variables) and redeploy, or set it in a local .env file, or set "
                "TTS_PROVIDER=gemini to use Gemini TTS instead."
            ),
        )

    voice_a, voice_b = await resolve_voice_ids(api_key)
    voice_id = voice_a if speaker == 0 else voice_b
    url = f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}"

    async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(
                url,
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": api_key},
                json={
                    "text": text,
                    "model_id": ELEVENLABS_MODEL,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            )
        except httpx.HTTPError as exc:
            _log_upstream("elevenlabs tts connection", exc)
            raise HTTPException(status_code=502, detail="Could not reach the ElevenLabs service. Please try again.") from exc

    if response.status_code != 200:
        try:
            detail = response.json()["detail"]
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
        except Exception:
            message = response.text[:300]
        _log_upstream("elevenlabs tts", f"{response.status_code} {message}")
        raise HTTPException(status_code=502, detail="The ElevenLabs service returned an error. Please try again.")

    return response.content, "audio/mpeg"
