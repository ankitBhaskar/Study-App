"""Google Cloud Text-to-Speech provider (the default, TTS_PROVIDER=google)."""

from __future__ import annotations

import base64
from typing import Any

import httpx
from fastapi import HTTPException

from ..config import (
    GOOGLE_TTS_API_BASE,
    GOOGLE_TTS_MAX_INPUT_BYTES,
    GOOGLE_TTS_TIMEOUT_SECONDS,
    GOOGLE_TTS_VOICE,
    get_google_tts_api_key,
)
from ..utils import _log_upstream
from .pcm import parse_wav, pcm_to_wav, split_pcm_by_chars


async def _google_tts_request(text: str, audio_config: dict[str, Any]) -> bytes:
    """One Cloud Text-to-Speech synthesize call; returns the decoded audio
    bytes. Unlike Gemini TTS this is a dedicated speech engine, not an LLM —
    a full 4,500-char script synthesizes in seconds, so a whole episode fits
    in one call without ever nearing the serverless deadline."""
    api_key = get_google_tts_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google TTS API key is not configured. Set GOOGLE_TTS_API_KEY (or GEMINI_API_KEY) in your "
                "Vercel project settings and redeploy."
            ),
        )

    # "en-US-Neural2-F" → languageCode "en-US"
    language_code = "-".join(GOOGLE_TTS_VOICE.split("-")[:2]) or "en-US"
    body = {
        "input": {"text": text},
        "voice": {"languageCode": language_code, "name": GOOGLE_TTS_VOICE},
        "audioConfig": audio_config,
    }

    async with httpx.AsyncClient(timeout=GOOGLE_TTS_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(
                f"{GOOGLE_TTS_API_BASE}/text:synthesize",
                headers={"x-goog-api-key": api_key},
                json=body,
            )
        except httpx.HTTPError as exc:
            _log_upstream("google tts connection", exc)
            raise HTTPException(status_code=502, detail="Could not reach the Google TTS service. Please try again.") from exc

    if response.status_code != 200:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = response.text[:500]
        _log_upstream("google tts", f"{response.status_code} {message}")
        if response.status_code == 403 and "texttospeech.googleapis.com" in message:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Google Cloud Text-to-Speech isn't enabled for this key's project. Enable it at "
                    "https://console.cloud.google.com/apis/library/texttospeech.googleapis.com"
                ),
            )
        raise HTTPException(status_code=502, detail="The Google TTS service returned an error. Please try again.")

    try:
        return base64.b64decode(response.json()["audioContent"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=502, detail="Google TTS returned an unexpected response shape.")


async def _google_tts_synthesize(text: str) -> tuple[bytes, int]:
    """LINEAR16 synthesize call. Returns (pcm, sample_rate)."""
    wav = await _google_tts_request(text, {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000})
    return parse_wav(wav)


def _episode_text_slices(lines: list[str]) -> list[tuple[int, int]]:
    """Pack whole segments into as few synthesize calls as fit Cloud TTS's
    input-byte limit — normally exactly one for a ≤4,500-char script; only
    multi-byte punctuation pushing past the budget forces a second."""
    slices: list[tuple[int, int]] = []
    start = 0
    size = 0
    for index, line in enumerate(lines):
        line_bytes = len(line.encode("utf-8")) + 2  # +2 for the "\n\n" joiner
        if size and size + line_bytes > GOOGLE_TTS_MAX_INPUT_BYTES:
            slices.append((start, index))
            start = index
            size = 0
        size += line_bytes
    slices.append((start, len(lines)))
    return slices


async def google_tts_episode_track(transcript: list[dict[str, Any]]) -> bytes:
    """Generate the WHOLE episode as ONE continuous MP3 track. MP3 keeps a
    5-minute episode around ~1.2 MB — inside Vercel's response-body limit,
    unlike a ~14 MB uncompressed WAV. In the rare multi-slice case the MP3
    parts are concatenated (same encoder/settings, so players read the
    frames straight through). One WaveNet voice narrates everything."""
    lines = [str(seg.get("line") or "") for seg in transcript]
    parts: list[bytes] = []
    for slice_start, slice_end in _episode_text_slices(lines):
        text = "\n\n".join(lines[slice_start:slice_end])
        parts.append(
            await _google_tts_request(text, {"audioEncoding": "MP3", "sampleRateHertz": 24000})
        )
    return b"".join(parts)


async def google_tts(text: str) -> tuple[bytes, str]:
    """Generate one ad-hoc segment via Cloud TTS. Returns (wav_bytes, mime)."""
    pcm, sample_rate = await _google_tts_synthesize(text)
    return pcm_to_wav(pcm, sample_rate), "audio/wav"


async def google_tts_episode(transcript: list[dict[str, Any]]) -> list[tuple[int, bytes, str]]:
    """Generate the WHOLE episode via Cloud TTS — normally in exactly one
    synthesize call — split into per-segment WAV clips for the per-segment
    player/cache (used when a client asks for individual segments). One
    WaveNet voice narrates every segment; WaveNet has no multi-speaker
    mode."""
    lines = [str(seg.get("line") or "") for seg in transcript]
    results: list[tuple[int, bytes, str]] = []
    for slice_start, slice_end in _episode_text_slices(lines):
        text = "\n\n".join(lines[slice_start:slice_end])
        pcm, sample_rate = await _google_tts_synthesize(text)
        char_counts = [max(len(line), 1) for line in lines[slice_start:slice_end]]
        for offset, chunk in enumerate(split_pcm_by_chars(pcm, char_counts)):
            results.append((slice_start + offset, pcm_to_wav(chunk, sample_rate), "audio/wav"))
    return results
