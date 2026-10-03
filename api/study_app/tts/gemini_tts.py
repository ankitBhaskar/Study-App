"""Gemini TTS provider (opt-in via TTS_PROVIDER=gemini) — an LLM-based speech
model, batched to stay within the serverless request deadline and the free
tier's rate limit."""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx
from fastapi import HTTPException

from ..config import (
    GEMINI_API_BASE,
    GEMINI_TTS_BATCH_CHARS,
    GEMINI_TTS_MODEL,
    GEMINI_TTS_TIMEOUT_SECONDS,
    GEMINI_TTS_VOICE_A,
    GEMINI_TTS_VOICE_B,
    get_gemini_api_key,
)
from ..utils import _log_upstream
from .pcm import pcm_to_wav, split_pcm_by_chars


async def gemini_tts(text: str, speaker: int) -> tuple[bytes, str]:
    """Generate one segment via Gemini TTS. Returns (wav_bytes, mime)."""
    api_key = get_gemini_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Gemini API key is not configured. Add GEMINI_API_KEY in your Vercel project settings "
                "(Settings → Environment Variables) and redeploy, or set it in a local .env file."
            ),
        )

    voice = GEMINI_TTS_VOICE_A if speaker == 0 else GEMINI_TTS_VOICE_B
    url = f"{GEMINI_API_BASE}/models/{GEMINI_TTS_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }

    async with httpx.AsyncClient(timeout=GEMINI_TTS_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(url, headers={"x-goog-api-key": api_key}, json=body)
        except httpx.HTTPError as exc:
            _log_upstream("gemini tts connection", exc)
            raise HTTPException(status_code=502, detail="Could not reach the Gemini service. Please try again.") from exc

    if response.status_code != 200:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = response.text[:500]
        _log_upstream("gemini tts", f"{response.status_code} {message}")
        raise HTTPException(status_code=502, detail="The Gemini speech service returned an error. Please try again.")

    data = response.json()
    try:
        part = data["candidates"][0]["content"]["parts"][0]
        inline = part.get("inlineData") or part.get("inline_data")
        pcm = base64.b64decode(inline["data"])
        mime = inline.get("mimeType") or inline.get("mime_type") or ""
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="Gemini TTS returned an unexpected response shape.")

    # mimeType looks like "audio/L16;codec=pcm;rate=24000" — pull the rate.
    match = re.search(r"rate=(\d+)", mime)
    sample_rate = int(match.group(1)) if match else 24000
    return pcm_to_wav(pcm, sample_rate), "audio/wav"


def _tts_batch_bounds(transcript: list[dict[str, Any]], segment_index: int) -> tuple[int, int]:
    """Group consecutive segments into batches of at most
    GEMINI_TTS_BATCH_CHARS spoken characters and return the [start, end)
    bounds of the batch containing segment_index. Batching exists because a
    full 4,500-char script is ~5 minutes of audio — one Gemini call for all
    of it outlives the serverless request window (observed as 504s in
    production) — while per-segment calls trip the free tier's
    3-requests/minute limit. A batch is the middle ground: at most 2 calls
    for a max-length script, each finishing well inside maxDuration."""
    start = 0
    batch_chars = 0
    for index, seg in enumerate(transcript):
        line_chars = max(len(str(seg.get("line") or "")), 1)
        if batch_chars and batch_chars + line_chars > GEMINI_TTS_BATCH_CHARS:
            if index > segment_index:
                return start, index
            start = index
            batch_chars = 0
        batch_chars += line_chars
    return start, len(transcript)


async def gemini_tts_batch(
    transcript: list[dict[str, Any]], hosts: list[str], segment_index: int
) -> list[tuple[int, bytes, str]]:
    """Generate audio for the batch of consecutive segments containing
    segment_index in a single Gemini call (using multi-speaker TTS when
    there are two hosts), then slice the combined PCM into per-segment WAV
    clips. Returns (absolute_segment_index, wav_bytes, mime) tuples. This
    replaces calling gemini_tts() once per segment — up to a dozen calls
    for one episode — with one call per ~GEMINI_TTS_BATCH_CHARS characters,
    which stays under both the free-tier rate limit and the serverless
    request deadline."""
    api_key = get_gemini_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Gemini API key is not configured. Add GEMINI_API_KEY in your Vercel project settings "
                "(Settings → Environment Variables) and redeploy, or set it in a local .env file."
            ),
        )

    host_a = (hosts[0] if hosts else "") or "Host A"
    host_b = (hosts[1] if len(hosts) > 1 else "") or "Host B"
    if host_b == host_a:
        host_b = f"{host_a} 2"

    batch_start, batch_end = _tts_batch_bounds(transcript, segment_index)
    batch = transcript[batch_start:batch_end]
    lines = [str(seg.get("line") or "") for seg in batch]
    # Match the frontend's own speaker-index mapping (seg.who === hosts[0] ?
    # 0 : 1) so cached audio lines up with which voice the UI expects.
    labels = [host_a if str(seg.get("who")) == (hosts[0] if hosts else host_a) else host_b for seg in batch]
    speaker_count = len(set(labels))

    combined_text = "\n".join(f"{label}: {line}" for label, line in zip(labels, lines))
    generation_config: dict[str, Any] = {"responseModalities": ["AUDIO"]}
    if speaker_count <= 1:
        generation_config["speechConfig"] = {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_TTS_VOICE_A}}
        }
    else:
        generation_config["speechConfig"] = {
            "multiSpeakerVoiceConfig": {
                "speakerVoiceConfigs": [
                    {"speaker": host_a, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_TTS_VOICE_A}}},
                    {"speaker": host_b, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_TTS_VOICE_B}}},
                ]
            }
        }

    url = f"{GEMINI_API_BASE}/models/{GEMINI_TTS_MODEL}:generateContent"
    body = {"contents": [{"parts": [{"text": combined_text}]}], "generationConfig": generation_config}

    async with httpx.AsyncClient(timeout=GEMINI_TTS_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(url, headers={"x-goog-api-key": api_key}, json=body)
        except httpx.HTTPError as exc:
            _log_upstream("gemini tts connection", exc)
            raise HTTPException(status_code=502, detail="Could not reach the Gemini service. Please try again.") from exc

    if response.status_code != 200:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = response.text[:500]
        _log_upstream("gemini tts", f"{response.status_code} {message}")
        raise HTTPException(status_code=502, detail="The Gemini speech service returned an error. Please try again.")

    data = response.json()
    try:
        part = data["candidates"][0]["content"]["parts"][0]
        inline = part.get("inlineData") or part.get("inline_data")
        pcm = base64.b64decode(inline["data"])
        mime = inline.get("mimeType") or inline.get("mime_type") or ""
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="Gemini TTS returned an unexpected response shape.")

    match = re.search(r"rate=(\d+)", mime)
    sample_rate = int(match.group(1)) if match else 24000

    char_counts = [max(len(line), 1) for line in lines]
    pcm_chunks = split_pcm_by_chars(pcm, char_counts)
    return [
        (batch_start + offset, pcm_to_wav(chunk, sample_rate), "audio/wav")
        for offset, chunk in enumerate(pcm_chunks)
    ]
