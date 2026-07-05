from __future__ import annotations

import os

import httpx
from fastapi import HTTPException

from .base import VoiceRequest, VoiceResponse


class OpenAIVoiceProvider:
    provider_name = "openai"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
        self.base_url = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

    async def generate_audio(self, request: VoiceRequest) -> VoiceResponse:
        if not self.api_key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")

        payload = {
            "model": self.model,
            "voice": request.voice or "alloy",
            "input": request.text,
            "format": "mp3",
            "speed": request.speed,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/audio/speech", headers=headers, json=payload)

        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"OpenAI TTS error ({response.status_code}): {response.text[:500]}")

        return VoiceResponse(
            audio=response.content,
            media_type=response.headers.get("content-type", "audio/mpeg"),
            provider=self.provider_name,
            model=self.model,
        )
