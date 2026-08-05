"""Podcast script regeneration and per-provider audio generation/caching."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..auth import require_user
from ..config import MAX_SEGMENT_TEXT_CHARS, TTS_PROVIDER
from ..firebase_client import get_firestore_client
from ..gemini_client import call_gemini, parse_json_text
from ..models import (
    AudioStatusResponse,
    AuthedUser,
    EpisodeAudioRequest,
    Podcast,
    PodcastRegenerateRequest,
    PodcastRegenerateResponse,
    SegmentAudioRequest,
)
from ..storage.audio_cache import (
    _active_audio_ns,
    _audio_collection_ref,
    _audio_segment_ref,
    get_cached_segment_audio,
    list_cached_segment_indices,
    save_segment_audio,
)
from ..storage.documents import _get_document_or_404, _guess_podcast_style, _require_document_context
from ..storage.usage import reserve_usage
from ..study_parsing import parse_podcast_script
from ..study_prompts import PODCAST_STYLES, build_podcast_system_instruction
from ..tts.elevenlabs import elevenlabs_tts
from ..tts.gemini_tts import gemini_tts, gemini_tts_batch
from ..tts.google_tts import google_tts, google_tts_episode, google_tts_episode_track

router = APIRouter()


@router.post("/api/documents/{doc_id}/podcast/regenerate", response_model=PodcastRegenerateResponse)
async def regenerate_podcast(
    doc_id: str, request: PodcastRegenerateRequest, user: AuthedUser = Depends(require_user)
) -> PodcastRegenerateResponse:
    doc_ref, data = _get_document_or_404(user.uid, doc_id)

    style = request.style if request.style in PODCAST_STYLES else "conversation"

    # One-time migration for documents saved before style versioning: adopt
    # the current script as the saved version of its (guessed) style, keeping
    # its already-cached audio reachable via the legacy namespace.
    versions: dict[str, Any] = dict(data.get("podcast_versions") or {})
    if not versions:
        current = data.get("podcast") or {}
        if current.get("transcript"):
            versions[_guess_podcast_style(current)] = {**current, "audio_ns": "legacy"}

    # Already generated in this style? Load it from storage — no Gemini
    # call, no usage charge, and its cached audio (own namespace) survives.
    saved = versions.get(style)
    if isinstance(saved, dict) and saved.get("transcript"):
        podcast = Podcast(**saved)
        doc_ref.update(
            {"podcast": podcast.model_dump(), "podcast_style": style, "podcast_versions": versions}
        )
        return PodcastRegenerateResponse(
            podcast=podcast, podcast_style=style, saved_styles=sorted(versions), reused=True
        )

    reserve_usage(user.uid)
    context = _require_document_context(data, "podcast script")
    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        f"File name: {data.get('file_name', 'uploaded-document.pdf')}\n\n"
                        "Document content:\n\n"
                        f"{context}"
                    )
                }
            ],
        }
    ]
    raw_text = await call_gemini(build_podcast_system_instruction(style), contents, json_response=True)
    podcast = parse_podcast_script(parse_json_text(raw_text))
    if podcast is None:
        raise HTTPException(status_code=502, detail="Gemini response did not include a usable podcast script.")

    # Only this style's audio namespace could hold stale clips (defensive —
    # a fresh style normally has none); other styles' audio is untouched so
    # switching back to them stays free.
    db = get_firestore_client()
    if db is not None:
        prefix = f"{style}."
        for audio_doc in _audio_collection_ref(db, user.uid, doc_id).select(["__name__"]).stream():
            if audio_doc.id.startswith(prefix):
                audio_doc.reference.delete()

    versions[style] = {**podcast.model_dump(), "audio_ns": style}
    doc_ref.update({"podcast": podcast.model_dump(), "podcast_style": style, "podcast_versions": versions})
    return PodcastRegenerateResponse(
        podcast=podcast, podcast_style=style, saved_styles=sorted(versions), reused=False
    )


@router.get("/api/podcast/audio-status/{doc_id}", response_model=AudioStatusResponse)
async def podcast_audio_status(
    doc_id: str, user: AuthedUser = Depends(require_user)
) -> AudioStatusResponse:
    # Lets the frontend restore the player after a reload: it reports which
    # of the ACTIVE style's segments already have saved audio, so cached
    # playback needs no new TTS calls (and no usage-limit hits).
    db = get_firestore_client()
    ns = "legacy"
    if db is not None:
        snapshot = db.collection("users").document(user.uid).collection("documents").document(doc_id).get()
        if snapshot.exists:
            ns = _active_audio_ns(snapshot.to_dict() or {})
    episode_cached = False
    if db is not None:
        # Field-mask read: answers "is the full-episode track cached?"
        # without downloading megabytes of base64 audio.
        full_snapshot = _audio_segment_ref(db, user.uid, doc_id, ns, "full").get(field_paths=["chunks"])
        episode_cached = full_snapshot.exists
    return AudioStatusResponse(
        cached_segments=list_cached_segment_indices(user.uid, doc_id, ns),
        episode_cached=episode_cached,
    )


@router.post("/api/podcast/segment-audio")
async def podcast_segment_audio(
    request: SegmentAudioRequest, user: AuthedUser = Depends(require_user)
) -> Response:
    has_cache_key = request.document_id and request.segment_index is not None
    # The document (when given) determines both the audio-cache namespace of
    # its active style and the transcript for batch generation — fetch it
    # once, before the cache check.
    doc_data: dict[str, Any] | None = None
    ns = "legacy"
    if has_cache_key:
        db = get_firestore_client()
        doc_snapshot = (
            db.collection("users").document(user.uid).collection("documents").document(request.document_id).get()
            if db is not None
            else None
        )
        doc_data = doc_snapshot.to_dict() if doc_snapshot is not None and doc_snapshot.exists else None
        ns = _active_audio_ns(doc_data or {})
        cached = get_cached_segment_audio(user.uid, request.document_id, ns, request.segment_index)
        if cached:
            audio_bytes, mime = cached
            return Response(content=audio_bytes, media_type=mime)

    reserve_usage(user.uid)

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Segment text must not be empty.")
    if len(text) > MAX_SEGMENT_TEXT_CHARS:
        raise HTTPException(status_code=400, detail="Segment text is too long for audio generation.")

    # Provider dispatch — all three code paths are kept; TTS_PROVIDER picks
    # one. ElevenLabs stays one call per segment (no batch mode there).
    if TTS_PROVIDER == "elevenlabs":
        audio_bytes, mime = await elevenlabs_tts(text, request.speaker)
        if has_cache_key:
            save_segment_audio(user.uid, request.document_id, ns, request.segment_index, audio_bytes, mime)
        return Response(content=audio_bytes, media_type=mime)

    # For a request tied to a saved document, generate many segments at once
    # from the stored transcript and cache them all:
    #   google (default): the ENTIRE episode in one fast Cloud TTS call
    #   gemini: the batch of ~2,250 chars around the requested segment
    episode_result: list[tuple[int, bytes, str]] | None = None
    if has_cache_key:
        podcast_data = (doc_data or {}).get("podcast") or {}
        transcript = podcast_data.get("transcript") or []
        hosts = podcast_data.get("hosts") or []
        if transcript and request.segment_index < len(transcript):
            if TTS_PROVIDER == "gemini":
                episode_result = await gemini_tts_batch(transcript, hosts, request.segment_index)
            else:
                episode_result = await google_tts_episode(transcript)

    if episode_result is not None:
        requested: tuple[bytes, str] | None = None
        for index, seg_bytes, seg_mime in episode_result:
            save_segment_audio(user.uid, request.document_id, ns, index, seg_bytes, seg_mime)
            if index == request.segment_index:
                requested = (seg_bytes, seg_mime)
        if requested is None:
            raise HTTPException(status_code=502, detail="Audio generation did not cover the requested segment.")
        audio_bytes, mime = requested
        return Response(content=audio_bytes, media_type=mime)

    # Fallback: no saved document to read the full script from (or the
    # index didn't line up with it) — generate just this one segment.
    if TTS_PROVIDER == "gemini":
        audio_bytes, mime = await gemini_tts(text, request.speaker)
    else:
        audio_bytes, mime = await google_tts(text)
    if has_cache_key:
        save_segment_audio(user.uid, request.document_id, ns, request.segment_index, audio_bytes, mime)
    return Response(content=audio_bytes, media_type=mime)


@router.post("/api/podcast/episode-audio")
async def podcast_episode_audio(
    request: EpisodeAudioRequest, user: AuthedUser = Depends(require_user)
) -> Response:
    """The whole episode as ONE continuous MP3 track (Google Cloud TTS only).
    The frontend prefers this over per-segment clips: one request, one audio
    element, seamless playback with real seeking. Falls back to 404 for the
    other providers so the caller can use the per-segment flow instead."""
    if TTS_PROVIDER != "google":
        raise HTTPException(status_code=404, detail="Episode audio is only available with the Google TTS provider.")

    db = get_firestore_client()
    doc_snapshot = (
        db.collection("users").document(user.uid).collection("documents").document(request.document_id).get()
        if db is not None
        else None
    )
    doc_data = doc_snapshot.to_dict() if doc_snapshot is not None and doc_snapshot.exists else None
    if doc_data is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    ns = _active_audio_ns(doc_data)

    cached = get_cached_segment_audio(user.uid, request.document_id, ns, "full")
    if cached:
        audio_bytes, mime = cached
        return Response(content=audio_bytes, media_type=mime)

    transcript = ((doc_data.get("podcast") or {}).get("transcript")) or []
    if not transcript:
        raise HTTPException(status_code=400, detail="This document has no podcast script to narrate.")

    reserve_usage(user.uid)
    mp3 = await google_tts_episode_track(transcript)
    save_segment_audio(user.uid, request.document_id, ns, "full", mp3, "audio/mpeg")
    return Response(content=mp3, media_type="audio/mpeg")
