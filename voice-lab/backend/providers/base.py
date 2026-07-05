from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VoiceRequest:
    text: str
    voice: str | None = None
    speed: float = 1.0


@dataclass(frozen=True)
class VoiceResponse:
    audio: bytes
    media_type: str
    provider: str
    model: str


class VoiceProvider(Protocol):
    provider_name: str

    async def generate_audio(self, request: VoiceRequest) -> VoiceResponse:
        """Generate audio bytes from text."""
