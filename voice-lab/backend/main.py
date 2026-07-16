from __future__ import annotations

import os
import time
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from providers import ElevenLabsVoiceProvider, GeminiVoiceProvider, OpenAIVoiceProvider, VoiceRequest

load_dotenv()

ProviderName = Literal["gemini", "openai", "elevenlabs"]


class GenerateVoiceRequest(BaseModel):
    provider: ProviderName
    text: str = Field(..., min_length=1, max_length=5_000)
    voice: str | None = None
    speed: float = Field(1.0, ge=0.5, le=2.0)


class ProviderStatus(BaseModel):
    configured: bool
    model: str


class HealthResponse(BaseModel):
    status: str
    providers: dict[str, ProviderStatus]


allowed_origins = [
    origin.strip()
    for origin in os.getenv("VOICE_LAB_ALLOWED_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174").split(",")
    if origin.strip()
]

app = FastAPI(
    title="Voice Lab API",
    version="0.1.0",
    description="Isolated voice provider comparison POC for Gemini, OpenAI and ElevenLabs.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def provider_map():
    return {
        "gemini": GeminiVoiceProvider(),
        "openai": OpenAIVoiceProvider(),
        "elevenlabs": ElevenLabsVoiceProvider(),
    }


@app.get("/api/voice/health", response_model=HealthResponse)
def health() -> HealthResponse:
    providers = provider_map()
    return HealthResponse(
        status="ok",
        providers={
            "gemini": ProviderStatus(configured=bool(providers["gemini"].api_key), model=providers["gemini"].model),
            "openai": ProviderStatus(configured=bool(providers["openai"].api_key), model=providers["openai"].model),
            "elevenlabs": ProviderStatus(configured=bool(providers["elevenlabs"].api_key), model=providers["elevenlabs"].model),
        },
    )


@app.post("/api/voice/generate")
async def generate_voice(request: GenerateVoiceRequest) -> Response:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text must not be empty.")

    providers = provider_map()
    provider = providers[request.provider]

    started = time.perf_counter()
    result = await provider.generate_audio(VoiceRequest(text=text, voice=request.voice, speed=request.speed))
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    return Response(
        content=result.audio,
        media_type=result.media_type,
        headers={
            "X-Voice-Provider": result.provider,
            "X-Voice-Model": result.model,
            "X-Voice-Latency-Ms": str(elapsed_ms),
            "X-Voice-Audio-Bytes": str(len(result.audio)),
        },
    )
