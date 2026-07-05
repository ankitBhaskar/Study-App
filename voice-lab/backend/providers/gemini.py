from __future__ import annotations

import base64
import os

import httpx
from fastapi import HTTPException

from .base import VoiceRequest, VoiceResponse


class GeminiVoiceProvider:
    provider_name = "gemini"

    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
        self.base_url = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")

    async def generate_audio(self, request: VoiceRequest) -> VoiceResponse:
        if not self.api_key:
            raise HTTPException(status_code=503, detail="GEMINI_API_KEY or GOOGLE_API_KEY is not configured.")

        voice_name = request.voice or "Kore"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": request.text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice_name}
                    }
                },
            },
        }

        url = f"{self.base_url}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)

        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Gemini TTS error ({response.status_code}): {response.text[:500]}")

        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as exc:
            raise HTTPException(status_code=502, detail="Gemini returned an unexpected TTS response shape.") from exc

        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                media_type = inline_data.get("mimeType") or inline_data.get("mime_type") or "audio/wav"
                return VoiceResponse(
                    audio=base64.b64decode(inline_data["data"]),
                    media_type=media_type,
                    provider=self.provider_name,
                    model=self.model,
                )

        raise HTTPException(status_code=502, detail="Gemini did not return audio data.")
