"""Small stateless helpers shared across modules."""

from __future__ import annotations

from datetime import datetime, timezone


def _log_upstream(context: str, detail: object) -> None:
    """Record an upstream (Gemini/TTS/ElevenLabs) failure to the server logs
    (captured by Vercel) without echoing the raw provider response — or a
    connection error's internals — back to the client, where it's just free
    reconnaissance. Clients get a generic 502 message instead."""
    print(f"[upstream] {context}: {detail}", flush=True)


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
