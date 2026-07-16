from __future__ import annotations

import os

import httpx
from fastapi import HTTPException

from .base import VoiceRequest, VoiceResponse


class ElevenLabsVoiceProvider:
    provider_name = "elevenlabs"

    def __init__(self) -> None:
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.model = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
        self.base_url = os.getenv("ELEVENLABS_API_BASE", "https://api.elevenlabs.io/v1")
        self.default_voice_id = os.getenv("ELEVENLABS_VOICE_ID")

    async def _resolve_voice_id(self) -> str:
        if self.default_voice_id:
            return self.default_voice_id
        if not self.api_key:
            raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY is not configured.")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(f"{self.base_url}/voices", headers={"xi-api-key": self.api_key})

        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"ElevenLabs voices error ({response.status_code}): {response.text[:500]}")

        voices = response.json().get("voices") or []
        if not voices:
            raise HTTPException(status_code=502, detail="No ElevenLabs voices are available in this account.")
        return voices[0]["voice_id"]

    async def generate_audio(self, request: VoiceRequest) -> VoiceResponse:
        if not self.api_key:
            raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY is not configured.")

        voice_id = request.voice or await self._resolve_voice_id()
        payload = {
            "text": request.text,
            "model_id": self.model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        headers = {"xi-api-key": self.api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/text-to-speech/{voice_id}", headers=headers, json=payload)

        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"ElevenLabs TTS error ({response.status_code}): {response.text[:500]}")

        return VoiceResponse(audio=response.content, media_type="audio/mpeg", provider=self.provider_name, model=self.model)
