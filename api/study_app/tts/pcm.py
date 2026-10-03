"""Raw PCM/WAV helpers shared by the Gemini and Google TTS providers."""

from __future__ import annotations

import struct

from fastapi import HTTPException


def pcm_to_wav(pcm: bytes, sample_rate: int, channels: int = 1, bits: int = 16) -> bytes:
    # Gemini TTS returns raw signed 16-bit little-endian PCM; browsers won't
    # play that without a container, so wrap it in a minimal WAV header.
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


def split_pcm_by_chars(pcm: bytes, char_counts: list[int], bits: int = 16) -> list[bytes]:
    """Slice one combined PCM buffer into per-segment chunks, sized
    proportionally to each segment's share of the script's character count.
    This is a heuristic — spoken pacing isn't perfectly linear in text
    length — but it's the only boundary signal available once Gemini
    returns a single audio blob for a multi-segment script, and it keeps
    boundaries aligned to whole samples so no chunk starts mid-sample."""
    bytes_per_sample = bits // 8
    total_chars = sum(char_counts) or 1
    total_samples = len(pcm) // bytes_per_sample
    chunks: list[bytes] = []
    sample_cursor = 0
    chars_cursor = 0
    for index, chars in enumerate(char_counts):
        chars_cursor += chars
        if index == len(char_counts) - 1:
            end_sample = total_samples
        else:
            end_sample = round(total_samples * chars_cursor / total_chars)
        chunks.append(pcm[sample_cursor * bytes_per_sample : end_sample * bytes_per_sample])
        sample_cursor = end_sample
    return chunks


def parse_wav(wav: bytes) -> tuple[bytes, int]:
    """Extract (pcm, sample_rate) from a WAV container. Cloud TTS LINEAR16
    responses come with a WAV header; the PCM inside gets re-sliced per
    segment and re-wrapped by pcm_to_wav()."""
    if len(wav) < 44 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise HTTPException(status_code=502, detail="Google TTS returned audio in an unexpected format.")
    sample_rate = struct.unpack_from("<I", wav, 24)[0] or 24000
    data_pos = wav.find(b"data", 12)
    if data_pos == -1:
        raise HTTPException(status_code=502, detail="Google TTS returned audio in an unexpected format.")
    data_len = struct.unpack_from("<I", wav, data_pos + 4)[0]
    start = data_pos + 8
    return wav[start : start + data_len] if data_len else wav[start:], sample_rate
