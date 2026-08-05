"""Cached podcast segment/episode audio, stored as base64 under each
document's `audio` subcollection and namespaced per podcast style."""

from __future__ import annotations

import base64
from typing import Any

from ..config import MAX_CACHED_AUDIO_BYTES
from ..firebase_client import get_firestore_client


def _audio_doc_id(ns: str, segment_index: int | str) -> str:
    # Cached audio is namespaced per podcast style so switching styles keeps
    # every generated version's audio. "legacy" is the namespace of audio
    # cached before styles were versioned: plain integer document IDs.
    # segment_index is an int for per-segment clips or the sentinel "full"
    # for the single continuous whole-episode track; "full" never parses as
    # an int, so segment listings skip it and the namespace-prefix delete on
    # fresh regeneration still clears it.
    return str(segment_index) if ns == "legacy" else f"{ns}.{segment_index}"


def _audio_collection_ref(db, uid: str, doc_id: str):
    return (
        db.collection("users")
        .document(uid)
        .collection("documents")
        .document(doc_id)
        .collection("audio")
    )


def _audio_segment_ref(db, uid: str, doc_id: str, ns: str, segment_index: int | str):
    return _audio_collection_ref(db, uid, doc_id).document(_audio_doc_id(ns, segment_index))


def _audio_chunk_ref(db, uid: str, doc_id: str, ns: str, segment_index: int | str, chunk: int):
    # Overflow chunks live as sibling documents whose IDs never parse as a
    # segment (their suffix isn't an integer), so list_cached_segment_indices
    # skips them and the collection-wide delete loops still clean them up.
    return _audio_collection_ref(db, uid, doc_id).document(f"{_audio_doc_id(ns, segment_index)}.c{chunk}")


def _active_audio_ns(data: dict[str, Any]) -> str:
    # Which audio namespace the document's ACTIVE podcast script uses. A
    # version generated after style-versioning stores audio under its style
    # name; a version inherited from before it keeps the legacy integer IDs.
    style = data.get("podcast_style")
    versions = data.get("podcast_versions") or {}
    if style and isinstance(versions.get(style), dict):
        return versions[style].get("audio_ns") or style
    return "legacy"


def get_cached_segment_audio(uid: str, doc_id: str, ns: str, segment_index: int | str) -> tuple[bytes, str] | None:
    db = get_firestore_client()
    if db is None:
        return None
    snapshot = _audio_segment_ref(db, uid, doc_id, ns, segment_index).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    encoded = data.get("data")
    if not encoded:
        return None
    parts = [base64.b64decode(encoded)]
    # Segments larger than one Firestore document are stored as extra chunk
    # documents; docs written before chunking existed have no "chunks" field.
    for chunk in range(1, int(data.get("chunks") or 1)):
        chunk_snapshot = _audio_chunk_ref(db, uid, doc_id, ns, segment_index, chunk).get()
        chunk_data = (chunk_snapshot.to_dict() or {}) if chunk_snapshot.exists else {}
        chunk_encoded = chunk_data.get("data")
        if not chunk_encoded:
            return None  # incomplete cache entry — treat as a miss
        parts.append(base64.b64decode(chunk_encoded))
    # Older cached segments predate the stored mime field; they were all
    # ElevenLabs MP3s, so default to audio/mpeg.
    return b"".join(parts), data.get("mime", "audio/mpeg")


def save_segment_audio(uid: str, doc_id: str, ns: str, segment_index: int | str, audio_bytes: bytes, mime: str) -> None:
    db = get_firestore_client()
    if db is None:
        return
    # A separate document per segment (rather than a field on the parent
    # document) keeps each one under Firestore's 1 MiB cap; audio larger
    # than one document allows is split across sibling chunk documents.
    chunks = [
        audio_bytes[offset : offset + MAX_CACHED_AUDIO_BYTES]
        for offset in range(0, len(audio_bytes), MAX_CACHED_AUDIO_BYTES)
    ] or [b""]
    # Extra chunks go in first so a reader never sees the main document
    # pointing at chunks that don't exist yet.
    for chunk_index, chunk_bytes in enumerate(chunks[1:], start=1):
        _audio_chunk_ref(db, uid, doc_id, ns, segment_index, chunk_index).set(
            {"data": base64.b64encode(chunk_bytes).decode("ascii")}
        )
    _audio_segment_ref(db, uid, doc_id, ns, segment_index).set(
        {
            "data": base64.b64encode(chunks[0]).decode("ascii"),
            "mime": mime,
            "chunks": len(chunks),
        }
    )


def list_cached_segment_indices(uid: str, doc_id: str, ns: str) -> list[int]:
    db = get_firestore_client()
    if db is None:
        return []
    indices = []
    # Projecting to __name__ returns only the document IDs (the segment
    # indices), so the base64 audio payloads aren't downloaded just to
    # report which segments are cached. IDs are "{index}" (legacy ns) or
    # "{style}.{index}"; chunk docs ("….c{n}") and other namespaces fail the
    # int() parse or the prefix check and are skipped.
    prefix = "" if ns == "legacy" else f"{ns}."
    for snapshot in _audio_collection_ref(db, uid, doc_id).select(["__name__"]).stream():
        candidate = snapshot.id
        if prefix:
            if not candidate.startswith(prefix):
                continue
            candidate = candidate[len(prefix):]
        try:
            indices.append(int(candidate))
        except ValueError:
            continue
    return sorted(indices)
