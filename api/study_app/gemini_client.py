"""Low-level Gemini generateContent call and JSON response parsing."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from fastapi import HTTPException

from .config import GEMINI_API_BASE, GEMINI_MODEL, GEMINI_TIMEOUT_SECONDS, get_gemini_api_key
from .utils import _log_upstream


async def call_gemini(system_instruction: str, contents: list[dict[str, Any]], *, json_response: bool = True) -> str:
    api_key = get_gemini_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Gemini API key is not configured. Add GEMINI_API_KEY in your Vercel project settings "
                "(Settings → Environment Variables) and redeploy, or set it in a local .env file."
            ),
        )

    generation_config: dict[str, Any] = {
        "temperature": 0.3,
        "topP": 0.9,
        "maxOutputTokens": 16384,
    }
    if json_response:
        generation_config["responseMimeType"] = "application/json"

    body = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "generationConfig": generation_config,
    }
    url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent"

    async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(url, headers={"x-goog-api-key": api_key}, json=body)
        except httpx.HTTPError as exc:
            _log_upstream("gemini generateContent connection", exc)
            raise HTTPException(status_code=502, detail="Could not reach the Gemini service. Please try again.") from exc

    if response.status_code != 200:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = response.text[:500]
        _log_upstream("gemini generateContent", f"{response.status_code} {message}")
        raise HTTPException(status_code=502, detail="The Gemini service returned an error. Please try again.")

    data = response.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        raise HTTPException(status_code=502, detail="Gemini returned an unexpected response shape.")

    text = "".join(part.get("text", "") for part in parts)
    if not text.strip():
        raise HTTPException(status_code=502, detail="Gemini returned an empty response. The request may have been blocked.")
    return text


def parse_json_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Gemini did not return valid JSON study content.") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Gemini returned JSON that is not an object.")
    return parsed
