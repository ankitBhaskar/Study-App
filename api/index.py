from __future__ import annotations

import base64
import io
import json
import os
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import firebase_admin
import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials, firestore
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore as gcloud_firestore
from pydantic import BaseModel
from pypdf import PdfReader

load_dotenv()

APP_NAME = "Study App API"
# Vercel serverless functions reject request bodies over ~4.5 MB, so the
# upload limit must stay below that even though Gemini could handle more.
MAX_FILE_SIZE_BYTES = 4 * 1024 * 1024
DEFAULT_CHUNK_SIZE = 6_000
DEFAULT_CHUNK_OVERLAP = 600
# A 4 MB text-based PDF rarely extracts to more than this; ~400k chars is
# roughly 100k tokens, comfortably inside gemini-2.5-flash's 1M context.
MAX_GEMINI_CONTEXT_CHARS = 400_000
GEMINI_API_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_SECONDS = 55.0
ELEVENLABS_API_BASE = os.getenv("ELEVENLABS_API_BASE", "https://api.elevenlabs.io/v1")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
# Optional explicit overrides. Left unset, the two host voices are resolved
# at runtime from GET /v1/voices — free-tier ElevenLabs accounts get a 402
# calling the text-to-speech endpoint with a "voice library" ID that isn't
# already in their own account, so hardcoding well-known IDs (e.g. the
# premade Rachel/Adam voices) breaks for exactly those accounts. Reading the
# account's own voice list guarantees whatever we pick is actually usable.
ELEVENLABS_VOICE_HOST_A = os.getenv("ELEVENLABS_VOICE_HOST_A")
ELEVENLABS_VOICE_HOST_B = os.getenv("ELEVENLABS_VOICE_HOST_B")
ELEVENLABS_TIMEOUT_SECONDS = 55.0
# Which text-to-speech backend the podcast audio uses. Gemini TTS is far
# cheaper than ElevenLabs, so it's the default; set TTS_PROVIDER=elevenlabs
# to switch back (the ElevenLabs code path is kept intact, just not used
# unless selected). Gemini TTS reuses GEMINI_API_KEY.
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "gemini").strip().lower()
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
# Two prebuilt Gemini voices for the two hosts. Full list in Gemini's TTS
# docs (Kore, Puck, Charon, Fenrir, Aoede, Leda, Orus, Zephyr, …).
GEMINI_TTS_VOICE_A = os.getenv("GEMINI_TTS_VOICE_A", "Kore")
GEMINI_TTS_VOICE_B = os.getenv("GEMINI_TTS_VOICE_B", "Puck")
# Firestore caps a document at 1 MiB. ElevenLabs MP3 segments fit easily;
# Gemini TTS returns uncompressed PCM (wrapped as WAV) which can exceed that
# for a long line, so a segment above this raw-bytes threshold is served but
# not cached (base64 inflates ~4/3, leaving headroom under the 1 MiB cap).
MAX_CACHED_AUDIO_BYTES = 740_000
MAX_SEGMENT_TEXT_CHARS = 1_000
# Keeps each episode's total spoken text (all segment lines combined) short
# enough to stay cheap and fast to synthesize regardless of TTS provider.
# Enforced both in the prompt (so Gemini writes a shorter script) and in
# parse_podcast_script() (so a script that ignores the prompt still gets
# capped rather than trusted as-is).
MAX_PODCAST_SCRIPT_CHARS = 4_500
# Bound the persisted tutor transcript so it can't grow past Firestore's
# 1 MiB document cap: keep the most recent messages, each text truncated.
MAX_STORED_CHAT_MESSAGES = 60
MAX_STORED_CHAT_TEXT_BYTES = 10_000
# Firestore caps a document at 1 MiB (1,048,576 bytes) including every field;
# 900 KB of text leaves ~120 KB of headroom for the study data stored with it.
MAX_STORED_CONTEXT_BYTES = 900_000
# Keep only the most recent quiz attempts per document, and only look at a
# bounded number of past questions when asking Gemini to avoid repeats.
MAX_QUIZ_ATTEMPTS = 20
MAX_AVOID_QUESTIONS = 30
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY")
# Local dev/testing against the Firebase Local Emulator Suite needs no real
# service account — the emulator env vars are enough to talk to it.
USING_FIREBASE_EMULATOR = bool(os.getenv("FIRESTORE_EMULATOR_HOST") or os.getenv("FIREBASE_AUTH_EMULATOR_HOST"))
# Shared daily cap across document analysis, tutor chat and podcast audio —
# the three actions that call a paid API. One counter keeps this simple;
# split it into separate counters later if different limits are needed.
DAILY_USAGE_LIMIT = int(os.getenv("DAILY_USAGE_LIMIT", "100"))
# Comma-separated allowlist of emails permitted to use the app. Empty means
# unrestricted — set this to lock the app down to specific accounts.
ALLOWED_EMAILS = {e.strip().lower() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()}

app = FastAPI(
    title=APP_NAME,
    version="0.2.0",
    description="Extracts PDF text and generates study content (summary, quiz, podcast script, tutor chat) with Gemini.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PdfChunk(BaseModel):
    index: int
    text: str
    char_count: int


class GeminiPayload(BaseModel):
    model: str
    instruction: str
    contents: list[dict[str, Any]]
    generation_config: dict[str, Any]


class PdfProcessingResponse(BaseModel):
    file_name: str
    page_count: int
    char_count: int
    word_count: int
    preview: str
    chunks: list[PdfChunk]
    gemini_payload: GeminiPayload


@dataclass(frozen=True)
class ExtractedPdf:
    page_count: int
    text: str


class QuizQuestion(BaseModel):
    q: str
    options: list[str]
    answer: int
    topic: str = "General"
    explanation: str = ""


class PodcastSegment(BaseModel):
    t: str
    who: str
    line: str


class Podcast(BaseModel):
    duration: str
    hosts: list[str]
    transcript: list[PodcastSegment]


class StudyAnalysisResponse(BaseModel):
    file_name: str
    page_count: int
    title: str
    summary: list[str]
    quiz: list[QuizQuestion]
    podcast: Podcast
    # Serverless functions keep no state between requests, so the client
    # holds the extracted document text and sends it back with chat calls.
    document_context: str
    # Firestore document id, so the client can cache generated podcast audio
    # against this document and reuse it on a later visit. None if Firestore
    # isn't configured or the document couldn't be saved.
    document_id: str | None = None


class ChatTurn(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    document_context: str
    question: str
    file_name: str = "uploaded-document.pdf"
    history: list[ChatTurn] = []


class ChatResponse(BaseModel):
    answer: str


class ChatMessage(BaseModel):
    role: str
    text: str


class ChatLogRequest(BaseModel):
    messages: list[ChatMessage] = []


class ChatLogResponse(BaseModel):
    messages: list[ChatMessage]


class QuizAttemptRequest(BaseModel):
    questions: list[QuizQuestion]
    answers: list[int]


class QuizAttempt(BaseModel):
    id: str
    questions: list[QuizQuestion]
    answers: list[int]
    score: int
    total: int
    created_at: str


class QuizAttemptListResponse(BaseModel):
    attempts: list[QuizAttempt]


class QuizRegenerateResponse(BaseModel):
    quiz: list[QuizQuestion]


class SummaryRegenerateRequest(BaseModel):
    length: str = "concise"
    focus: str = ""


class SummaryRegenerateResponse(BaseModel):
    summary: list[str]


class PodcastRegenerateRequest(BaseModel):
    style: str = "conversation"


class PodcastRegenerateResponse(BaseModel):
    podcast: Podcast


class SegmentAudioRequest(BaseModel):
    text: str
    speaker: int = 0
    # Optional cache key: when both are given and the document belongs to
    # the caller, previously generated audio for this exact segment is
    # reused instead of calling ElevenLabs again.
    document_id: str | None = None
    segment_index: int | None = None


class AudioStatusResponse(BaseModel):
    cached_segments: list[int]


class AuthedUser(BaseModel):
    uid: str
    email: str | None = None


class ProfileResponse(BaseModel):
    uid: str
    email: str | None
    created_at: str
    usage_today: int
    daily_limit: int


class DocumentRecord(BaseModel):
    id: str
    title: str
    file_name: str
    created_at: str
    summary: list[str]
    quiz: list[QuizQuestion]
    podcast: Podcast


class DocumentDetail(DocumentRecord):
    document_context: str = ""


class DocumentListResponse(BaseModel):
    documents: list[DocumentRecord]


def get_gemini_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def get_elevenlabs_api_key() -> str | None:
    return os.getenv("ELEVENLABS_API_KEY")


_cached_voice_ids: tuple[str, str] | None = None


async def resolve_voice_ids(api_key: str) -> tuple[str, str]:
    global _cached_voice_ids

    if ELEVENLABS_VOICE_HOST_A and ELEVENLABS_VOICE_HOST_B:
        return ELEVENLABS_VOICE_HOST_A, ELEVENLABS_VOICE_HOST_B
    if _cached_voice_ids:
        return _cached_voice_ids

    async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT_SECONDS) as client:
        try:
            response = await client.get(f"{ELEVENLABS_API_BASE}/voices", headers={"xi-api-key": api_key})
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach the ElevenLabs API: {exc}") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Could not list ElevenLabs voices ({response.status_code}).")

    voices = response.json().get("voices") or []
    if len(voices) < 2:
        raise HTTPException(
            status_code=502,
            detail=(
                "Your ElevenLabs account has fewer than two voices available via the API. "
                "Add voices in the ElevenLabs dashboard (Voice Library → Add to my voices), "
                "or set ELEVENLABS_VOICE_HOST_A/ELEVENLABS_VOICE_HOST_B to specific voice IDs you own."
            ),
        )

    _cached_voice_ids = (voices[0]["voice_id"], voices[1]["voice_id"])
    return _cached_voice_ids


def firebase_configured() -> bool:
    return USING_FIREBASE_EMULATOR or bool(
        FIREBASE_PROJECT_ID and FIREBASE_CLIENT_EMAIL and FIREBASE_PRIVATE_KEY
    )


def get_firebase_app() -> firebase_admin.App | None:
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    if USING_FIREBASE_EMULATOR:
        return firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID or "demo-study-app"})

    if not firebase_configured():
        return None

    cred = credentials.Certificate(
        {
            "type": "service_account",
            "project_id": FIREBASE_PROJECT_ID,
            "client_email": FIREBASE_CLIENT_EMAIL,
            "private_key": FIREBASE_PRIVATE_KEY.replace("\\n", "\n"),
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    return firebase_admin.initialize_app(cred)


_emulator_firestore_client: gcloud_firestore.Client | None = None


def get_firestore_client():
    global _emulator_firestore_client

    if USING_FIREBASE_EMULATOR:
        # firebase_admin.firestore.client() eagerly resolves real Google
        # Application Default Credentials even when talking to the emulator,
        # which fails wherever ADC isn't configured. Anonymous credentials
        # sidestep that — the emulator never checks them anyway.
        if _emulator_firestore_client is None:
            _emulator_firestore_client = gcloud_firestore.Client(
                project=FIREBASE_PROJECT_ID or "demo-study-app",
                credentials=AnonymousCredentials(),
            )
        return _emulator_firestore_client

    app_instance = get_firebase_app()
    return firestore.client(app_instance) if app_instance else None


async def require_user(authorization: str | None = Header(default=None)) -> AuthedUser:
    if not firebase_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Login is not configured yet. Add FIREBASE_PROJECT_ID, FIREBASE_CLIENT_EMAIL and "
                "FIREBASE_PRIVATE_KEY in your Vercel project settings and redeploy."
            ),
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in required.")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        decoded = firebase_auth.verify_id_token(token, app=get_firebase_app())
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.") from exc

    email = decoded.get("email")
    if ALLOWED_EMAILS and (not email or email.lower() not in ALLOWED_EMAILS):
        raise HTTPException(status_code=403, detail="This app is invite-only. Contact the owner for access.")

    return AuthedUser(uid=decoded["uid"], email=email)


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _audio_segment_ref(db, uid: str, doc_id: str, segment_index: int):
    return (
        db.collection("users")
        .document(uid)
        .collection("documents")
        .document(doc_id)
        .collection("audio")
        .document(str(segment_index))
    )


def get_cached_segment_audio(uid: str, doc_id: str, segment_index: int) -> tuple[bytes, str] | None:
    db = get_firestore_client()
    if db is None:
        return None
    snapshot = _audio_segment_ref(db, uid, doc_id, segment_index).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    encoded = data.get("data")
    if not encoded:
        return None
    # Older cached segments predate the stored mime field; they were all
    # ElevenLabs MP3s, so default to audio/mpeg.
    return base64.b64decode(encoded), data.get("mime", "audio/mpeg")


def save_segment_audio(uid: str, doc_id: str, segment_index: int, audio_bytes: bytes, mime: str) -> None:
    db = get_firestore_client()
    if db is None:
        return
    # Uncompressed Gemini WAV can exceed Firestore's 1 MiB document cap for a
    # long line; skip caching those (they're still served, just regenerated
    # next time) rather than failing the write.
    if len(audio_bytes) > MAX_CACHED_AUDIO_BYTES:
        return
    # A separate document per segment (rather than a field on the parent
    # document) keeps each one well under Firestore's 1 MiB cap regardless
    # of how large the stored extracted text on the parent already is.
    _audio_segment_ref(db, uid, doc_id, segment_index).set(
        {"data": base64.b64encode(audio_bytes).decode("ascii"), "mime": mime}
    )


def _chat_log_ref(db, uid: str, doc_id: str):
    return (
        db.collection("users")
        .document(uid)
        .collection("documents")
        .document(doc_id)
        .collection("chat")
        .document("log")
    )


def _quiz_attempts_ref(db, uid: str, doc_id: str):
    return (
        db.collection("users")
        .document(uid)
        .collection("documents")
        .document(doc_id)
        .collection("quiz_attempts")
    )


def save_quiz_attempt(uid: str, doc_id: str, questions: list[QuizQuestion], answers: list[int]) -> QuizAttempt:
    # Score is derived here from each question's own correct-answer index,
    # never trusted from the caller.
    score = sum(1 for q, a in zip(questions, answers) if a == q.answer)
    created_at = datetime.now(timezone.utc).isoformat()

    db = get_firestore_client()
    if db is None:
        return QuizAttempt(id="", questions=questions, answers=answers, score=score, total=len(questions), created_at=created_at)

    attempts_ref = _quiz_attempts_ref(db, uid, doc_id)
    _, doc_ref = attempts_ref.add(
        {
            "questions": [q.model_dump() for q in questions],
            "answers": answers,
            "score": score,
            "total": len(questions),
            "created_at": created_at,
        }
    )
    # Bound the history the same way the chat log is bounded, just as
    # separate documents instead of a single truncated array: keep only the
    # most recent MAX_QUIZ_ATTEMPTS attempts.
    stale = list(
        attempts_ref.order_by("created_at", direction=firestore.Query.DESCENDING)
        .offset(MAX_QUIZ_ATTEMPTS)
        .stream()
    )
    for extra in stale:
        extra.reference.delete()

    return QuizAttempt(
        id=doc_ref.id, questions=questions, answers=answers, score=score, total=len(questions), created_at=created_at
    )


def list_quiz_attempts(uid: str, doc_id: str) -> list[QuizAttempt]:
    db = get_firestore_client()
    if db is None:
        return []
    query = (
        _quiz_attempts_ref(db, uid, doc_id)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(MAX_QUIZ_ATTEMPTS)
    )
    attempts = []
    for snapshot in query.stream():
        data = snapshot.to_dict() or {}
        attempts.append(
            QuizAttempt(
                id=snapshot.id,
                questions=[QuizQuestion(**q) for q in data.get("questions", [])],
                answers=data.get("answers", []),
                score=data.get("score", 0),
                total=data.get("total", 0),
                created_at=data.get("created_at", ""),
            )
        )
    return attempts


def list_cached_segment_indices(uid: str, doc_id: str) -> list[int]:
    db = get_firestore_client()
    if db is None:
        return []
    audio_ref = (
        db.collection("users")
        .document(uid)
        .collection("documents")
        .document(doc_id)
        .collection("audio")
    )
    indices = []
    # Projecting to __name__ returns only the document IDs (the segment
    # indices), so the base64 audio payloads aren't downloaded just to
    # report which segments are cached.
    for snapshot in audio_ref.select(["__name__"]).stream():
        try:
            indices.append(int(snapshot.id))
        except ValueError:
            continue
    return sorted(indices)


def check_usage_limit(uid: str) -> None:
    db = get_firestore_client()
    if db is None:
        return
    usage_ref = db.collection("users").document(uid).collection("usage").document(_today_key())
    snapshot = usage_ref.get()
    current = (snapshot.to_dict() or {}).get("count", 0) if snapshot.exists else 0
    if current >= DAILY_USAGE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"You've used all {DAILY_USAGE_LIMIT} AI actions for today. Please try again tomorrow.",
        )


def increment_usage(uid: str) -> None:
    db = get_firestore_client()
    if db is None:
        return
    usage_ref = db.collection("users").document(uid).collection("usage").document(_today_key())
    usage_ref.set({"count": firestore.Increment(1), "date": _today_key()}, merge=True)


def clean_pdf_text(raw_text: str) -> str:
    """Normalise PDF text extraction output for LLM use."""
    if not raw_text:
        return ""

    text = raw_text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_pdf_text(file_bytes: bytes) -> ExtractedPdf:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="The uploaded file could not be read as a valid PDF.") from exc

    page_text: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            extracted = page.extract_text() or ""
        except Exception:
            extracted = ""
        if extracted.strip():
            page_text.append(f"[Page {page_number}]\n{extracted}")

    text = clean_pdf_text("\n\n".join(page_text))
    return ExtractedPdf(page_count=len(reader.pages), text=text)


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[PdfChunk]:
    if not text:
        return []
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[PdfChunk] = []
    start = 0
    index = 1
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        candidate = text[start:end]

        if end < text_length:
            split_at = max(candidate.rfind(". "), candidate.rfind("\n"), candidate.rfind(" "))
            if split_at > int(chunk_size * 0.65):
                end = start + split_at + 1
                candidate = text[start:end]

        chunk = candidate.strip()
        if chunk:
            chunks.append(PdfChunk(index=index, text=chunk, char_count=len(chunk)))
            index += 1

        next_start = end - overlap
        start = max(next_start, end) if next_start <= start else next_start

    return chunks


def build_gemini_payload(file_name: str, chunks: list[PdfChunk]) -> GeminiPayload:
    combined_context = "\n\n".join(
        f"Document chunk {chunk.index}:\n{chunk.text}" for chunk in chunks
    )

    instruction = (
        "You are an expert study assistant. Use only the uploaded document content. "
        "Create a concise study summary, key concepts, quiz questions with answers, "
        "weak-topic hints, podcast talking points and tutor-ready context. "
        "Return structured JSON suitable for a study application."
    )

    return GeminiPayload(
        model=GEMINI_MODEL,
        instruction=instruction,
        contents=[
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"File name: {file_name}\n\n"
                            "Extracted PDF content prepared for analysis:\n\n"
                            f"{combined_context}"
                        )
                    }
                ],
            }
        ],
        generation_config={
            "temperature": 0.3,
            "top_p": 0.9,
            "max_output_tokens": 8192,
            "response_mime_type": "application/json",
        },
    )


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
            raise HTTPException(status_code=502, detail=f"Could not reach the Gemini API: {exc}") from exc

    if response.status_code != 200:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = response.text[:500]
        raise HTTPException(status_code=502, detail=f"Gemini API error ({response.status_code}): {message}")

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


PODCAST_STYLES = {"conversation", "solo", "interview"}
SUMMARY_LENGTHS = {"concise", "detailed"}

# Shared between the combined study-analysis prompt and the standalone
# regenerate-only prompts, so "New script" / a different length always reads
# consistently with what the first generation would have produced.
PODCAST_STYLE_GUIDANCE = {
    "conversation": (
        'Format: a natural two-host conversation. Invent two host names (e.g. "Maya" and "Theo") who '
        "banter naturally, ask each other questions, and build on what the other just said. Alternate "
        "speakers frequently so both hosts get airtime."
    ),
    "solo": (
        "Format: a single narrator speaking alone, like a solo explainer podcast. Invent one host name "
        'and use that same name as "speaker" for every segment. Write it as a flowing monologue that '
        "still sounds spoken, not read aloud — use rhetorical questions and asides to keep it engaging."
    ),
    "interview": (
        'Format: an interview. Invent two names: a "Host" who asks probing questions and a "Guest" '
        "presented as an expert on the material who answers in more depth. Have the Host ask short "
        "follow-up questions after the Guest's answers."
    ),
}

SUMMARY_LENGTH_GUIDANCE = {
    "concise": "Write 4 to 6 concise key-point strings covering the document.",
    "detailed": (
        "Write 8 to 12 detailed key-point strings covering the document, going deeper into mechanisms, "
        "numbers and examples than a brief overview would."
    ),
}


def _summary_instruction_line(length: str, focus: str) -> str:
    line = SUMMARY_LENGTH_GUIDANCE.get(length, SUMMARY_LENGTH_GUIDANCE["concise"])
    focus = focus.strip()
    if focus:
        line += (
            f' Focus specifically on this topic from the document: "{focus}" — '
            "skip parts of the document unrelated to it."
        )
    return line


def build_study_system_instruction(podcast_style: str, summary_length: str, summary_focus: str) -> str:
    summary_line = _summary_instruction_line(summary_length, summary_focus)
    podcast_line = PODCAST_STYLE_GUIDANCE.get(podcast_style, PODCAST_STYLE_GUIDANCE["conversation"])
    return f"""You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Create study material and return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{{
  "title": "short document title, e.g. chapter name",
  "summary": ["key-point strings covering the document"],
  "quiz": {{
    "questions": [
      {{
        "question": "string",
        "options": ["exactly 4 answer options"],
        "correctOptionIndex": 0,
        "explanation": "why the answer is correct",
        "topic": "short topic label"
      }}
    ]
  }},
  "podcastScript": {{
    "durationMinutes": 10,
    "hosts": ["name", ...],
    "segments": [
      {{"timestamp": "0:00", "speaker": "name", "line": "spoken line"}}
    ]
  }}
}}
Summary instructions: {summary_line}
Podcast instructions: {podcast_line} Create 8 to 12 podcast segments with timestamps spread between 0:00 and 9:30 in mm:ss format.
Keep the combined spoken text of all podcast segments under {MAX_PODCAST_SCRIPT_CHARS} characters total — write shorter, punchier lines rather than fewer segments.
Create 3 to 5 quiz questions. Everything must be grounded in the document content."""


def build_summary_system_instruction(length: str, focus: str) -> str:
    summary_line = _summary_instruction_line(length, focus)
    return f"""You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Generate a fresh summary of the document. Return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{{
  "summary": ["key-point strings covering the document"]
}}
{summary_line} Everything must be grounded in the document content."""


def build_podcast_system_instruction(style: str) -> str:
    podcast_line = PODCAST_STYLE_GUIDANCE.get(style, PODCAST_STYLE_GUIDANCE["conversation"])
    return f"""You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Generate a fresh podcast script grounded in the document. Return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{{
  "durationMinutes": 10,
  "hosts": ["name", ...],
  "segments": [
    {{"timestamp": "0:00", "speaker": "name", "line": "spoken line"}}
  ]
}}
{podcast_line} Create 8 to 12 segments with timestamps spread between 0:00 and 9:30 in mm:ss format. Everything must be grounded in the document content.
Keep the combined spoken text of all segments under {MAX_PODCAST_SCRIPT_CHARS} characters total — write shorter, punchier lines rather than fewer segments."""


QUIZ_SYSTEM_INSTRUCTION = """You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Generate a fresh set of 3 to 5 multiple-choice quiz questions grounded in the document. Return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{
  "questions": [
    {
      "question": "string",
      "options": ["exactly 4 answer options"],
      "correctOptionIndex": 0,
      "explanation": "why the answer is correct",
      "topic": "short topic label"
    }
  ]
}
Do not repeat any question with the same meaning as one listed under "Questions already used" below — write genuinely
different questions, ideally covering different parts of the document. Everything must be grounded in the document content."""


def parse_quiz_questions(quiz_raw: Any) -> list[QuizQuestion]:
    questions_raw = quiz_raw.get("questions") if isinstance(quiz_raw, dict) else quiz_raw
    quiz: list[QuizQuestion] = []
    for item in questions_raw or []:
        if not isinstance(item, dict):
            continue
        options = [str(opt) for opt in item.get("options") or []]
        try:
            answer = int(item.get("correctOptionIndex", item.get("answer", 0)))
        except (TypeError, ValueError):
            continue
        question_text = str(item.get("question") or item.get("q") or "").strip()
        if not question_text or len(options) < 2 or not 0 <= answer < len(options):
            continue
        quiz.append(
            QuizQuestion(
                q=question_text,
                options=options,
                answer=answer,
                topic=str(item.get("topic") or "General"),
                explanation=str(item.get("explanation") or ""),
            )
        )
    return quiz


def parse_summary_points(summary_raw: Any) -> list[str]:
    if isinstance(summary_raw, dict):
        summary_raw = summary_raw.get("detailedSummary") or [summary_raw.get("shortSummary", "")]
    return [str(point) for point in summary_raw or [] if str(point).strip()]


def parse_podcast_script(podcast_raw: dict[str, Any]) -> Podcast | None:
    hosts = [str(host) for host in podcast_raw.get("hosts") or []] or ["Maya", "Theo"]
    segments: list[PodcastSegment] = []
    # The prompt asks Gemini to stay under MAX_PODCAST_SCRIPT_CHARS, but LLMs
    # don't reliably self-count characters, so enforce it here too: stop
    # adding segments once the combined spoken text would cross the cap,
    # truncating (rather than dropping) an over-long segment so one runaway
    # line can't zero out an otherwise-good script.
    total_chars = 0
    for seg in podcast_raw.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        line = str(seg.get("line") or "").strip()
        if not line:
            continue
        remaining = MAX_PODCAST_SCRIPT_CHARS - total_chars
        if remaining <= 0:
            break
        if len(line) > remaining:
            line = line[:remaining].rstrip()
            if not line:
                break
        timestamp = str(seg.get("timestamp") or seg.get("t") or "0:00")
        if not re.fullmatch(r"\d{1,2}:\d{2}", timestamp):
            timestamp = "0:00"
        segments.append(PodcastSegment(t=timestamp, who=str(seg.get("speaker") or seg.get("who") or hosts[0]), line=line))
        total_chars += len(line)
    if not segments:
        return None

    try:
        duration_minutes = int(podcast_raw.get("durationMinutes") or 10)
    except (TypeError, ValueError):
        duration_minutes = 10
    # A solo-narrator script only has one host; conversation/interview have
    # two. Cap at 2 either way since that's all the ElevenLabs voice pipeline
    # (§ segment-audio) resolves.
    return Podcast(duration=f"{duration_minutes}:00", hosts=hosts[:2], transcript=segments)


def normalise_study_content(raw: dict[str, Any], file_name: str) -> tuple[str, list[str], list[QuizQuestion], Podcast]:
    title = str(raw.get("title") or file_name)

    summary = parse_summary_points(raw.get("summary"))
    if not summary:
        raise HTTPException(status_code=502, detail="Gemini response did not include a usable summary.")

    quiz = parse_quiz_questions(raw.get("quiz") or {})
    if not quiz:
        raise HTTPException(status_code=502, detail="Gemini response did not include usable quiz questions.")

    podcast = parse_podcast_script(raw.get("podcastScript") or {})
    if podcast is None:
        raise HTTPException(status_code=502, detail="Gemini response did not include a usable podcast script.")

    return title, summary, quiz, podcast


async def read_pdf_upload(file: UploadFile) -> ExtractedPdf:
    is_pdf_type = file.content_type in {"application/pdf", "application/x-pdf"}
    is_pdf_name = (file.filename or "").lower().endswith(".pdf")
    if not (is_pdf_type or is_pdf_name):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty.")
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="PDF is too large. Maximum supported size is 4 MB.")

    extracted = extract_pdf_text(file_bytes)
    if not extracted.text:
        raise HTTPException(
            status_code=422,
            detail="No readable text was found. This may be a scanned PDF and may need OCR before Gemini processing.",
        )
    return extracted


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": APP_NAME,
        "gemini_model": GEMINI_MODEL,
        "gemini_key_configured": bool(get_gemini_api_key()),
        "tts_provider": TTS_PROVIDER,
        "gemini_tts_model": GEMINI_TTS_MODEL,
        "elevenlabs_model": ELEVENLABS_MODEL,
        "elevenlabs_key_configured": bool(get_elevenlabs_api_key()),
        "firebase_configured": firebase_configured(),
        "daily_usage_limit": DAILY_USAGE_LIMIT,
        "access_restricted": bool(ALLOWED_EMAILS),
    }


@app.get("/api/profile", response_model=ProfileResponse)
async def get_profile(user: AuthedUser = Depends(require_user)) -> ProfileResponse:
    db = get_firestore_client()
    profile_ref = db.collection("users").document(user.uid)
    snapshot = profile_ref.get()
    if snapshot.exists:
        data = snapshot.to_dict() or {}
    else:
        data = {"email": user.email, "created_at": datetime.now(timezone.utc).isoformat()}
        profile_ref.set(data, merge=True)

    usage_snapshot = profile_ref.collection("usage").document(_today_key()).get()
    usage_today = (usage_snapshot.to_dict() or {}).get("count", 0) if usage_snapshot.exists else 0

    return ProfileResponse(
        uid=user.uid,
        email=data.get("email") or user.email,
        created_at=data.get("created_at", ""),
        usage_today=usage_today,
        daily_limit=DAILY_USAGE_LIMIT,
    )


@app.get("/api/documents", response_model=DocumentListResponse)
async def list_documents(user: AuthedUser = Depends(require_user)) -> DocumentListResponse:
    db = get_firestore_client()
    docs_ref = (
        db.collection("users")
        .document(user.uid)
        .collection("documents")
        # Field mask keeps the potentially-large document_context out of the
        # list query; it's fetched per-document via GET /api/documents/{id}.
        .select(["title", "file_name", "created_at", "summary", "quiz", "podcast"])
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(50)
    )
    records = []
    for doc in docs_ref.stream():
        data = doc.to_dict() or {}
        records.append(
            DocumentRecord(
                id=doc.id,
                title=data.get("title", "Untitled"),
                file_name=data.get("file_name", ""),
                created_at=data.get("created_at", ""),
                summary=data.get("summary", []),
                quiz=[QuizQuestion(**q) for q in data.get("quiz", [])],
                podcast=Podcast(**data.get("podcast", {"duration": "0:00", "hosts": [], "transcript": []})),
            )
        )
    return DocumentListResponse(documents=records)


@app.get("/api/documents/{doc_id}", response_model=DocumentDetail)
async def get_document(doc_id: str, user: AuthedUser = Depends(require_user)) -> DocumentDetail:
    db = get_firestore_client()
    snapshot = db.collection("users").document(user.uid).collection("documents").document(doc_id).get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Document not found.")
    data = snapshot.to_dict() or {}
    return DocumentDetail(
        id=snapshot.id,
        title=data.get("title", "Untitled"),
        file_name=data.get("file_name", ""),
        created_at=data.get("created_at", ""),
        summary=data.get("summary", []),
        quiz=[QuizQuestion(**q) for q in data.get("quiz", [])],
        podcast=Podcast(**data.get("podcast", {"duration": "0:00", "hosts": [], "transcript": []})),
        document_context=data.get("document_context", ""),
    )


def _delete_document_and_subcollections(doc_ref) -> None:
    # Firestore doesn't cascade-delete subcollections, so cached audio,
    # saved tutor chat and quiz-attempt history would otherwise be orphaned
    # (unreachable but still stored).
    for audio_doc in doc_ref.collection("audio").stream():
        audio_doc.reference.delete()
    for chat_doc in doc_ref.collection("chat").stream():
        chat_doc.reference.delete()
    for attempt_doc in doc_ref.collection("quiz_attempts").stream():
        attempt_doc.reference.delete()
    doc_ref.delete()


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, user: AuthedUser = Depends(require_user)) -> dict[str, str]:
    db = get_firestore_client()
    _delete_document_and_subcollections(
        db.collection("users").document(user.uid).collection("documents").document(doc_id)
    )
    return {"status": "deleted"}


@app.delete("/api/documents")
async def clear_documents(user: AuthedUser = Depends(require_user)) -> dict[str, str]:
    db = get_firestore_client()
    docs_ref = db.collection("users").document(user.uid).collection("documents")
    for doc in docs_ref.stream():
        _delete_document_and_subcollections(doc.reference)
    return {"status": "cleared"}


@app.post("/api/pdf/prepare", response_model=PdfProcessingResponse)
async def prepare_pdf(file: UploadFile = File(...)) -> PdfProcessingResponse:
    extracted = await read_pdf_upload(file)
    chunks = chunk_text(extracted.text)
    payload = build_gemini_payload(file.filename or "uploaded-document.pdf", chunks)
    words = re.findall(r"\b\w+\b", extracted.text)

    return PdfProcessingResponse(
        file_name=file.filename or "uploaded-document.pdf",
        page_count=extracted.page_count,
        char_count=len(extracted.text),
        word_count=len(words),
        preview=extracted.text[:1_000],
        chunks=chunks,
        gemini_payload=payload,
    )


@app.post("/api/pdf/analyze", response_model=StudyAnalysisResponse)
async def analyze_pdf(
    file: UploadFile = File(...),
    # Optional generation options — same choices exposed as "New questions" /
    # "New script" regeneration after the fact, but selectable up front too.
    podcast_style: str = Form("conversation"),
    summary_length: str = Form("concise"),
    summary_focus: str = Form(""),
    user: AuthedUser = Depends(require_user),
) -> StudyAnalysisResponse:
    check_usage_limit(user.uid)

    extracted = await read_pdf_upload(file)
    file_name = file.filename or "uploaded-document.pdf"
    context = extracted.text[:MAX_GEMINI_CONTEXT_CHARS]
    podcast_style = podcast_style if podcast_style in PODCAST_STYLES else "conversation"
    summary_length = summary_length if summary_length in SUMMARY_LENGTHS else "concise"
    summary_focus = summary_focus.strip()[:200]

    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        f"File name: {file_name}\n\n"
                        "Extracted PDF content:\n\n"
                        f"{context}"
                    )
                }
            ],
        }
    ]

    system_instruction = build_study_system_instruction(podcast_style, summary_length, summary_focus)
    raw_text = await call_gemini(system_instruction, contents, json_response=True)
    raw = parse_json_text(raw_text)
    title, summary, quiz, podcast = normalise_study_content(raw, file_name)

    increment_usage(user.uid)
    db = get_firestore_client()
    document_id = None
    if db is not None:
        # The PDF file itself is never stored — only the extracted text
        # (truncated to fit Firestore's 1 MiB document cap) and the derived
        # study data, so Tutor chat keeps working on history-reopened docs.
        _, doc_ref = db.collection("users").document(user.uid).collection("documents").add(
            {
                "title": title,
                "file_name": file_name,
                "summary": summary,
                "quiz": [q.model_dump() for q in quiz],
                "podcast": podcast.model_dump(),
                "document_context": truncate_utf8(context, MAX_STORED_CONTEXT_BYTES),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        document_id = doc_ref.id

    return StudyAnalysisResponse(
        file_name=file_name,
        page_count=extracted.page_count,
        title=title,
        summary=summary,
        quiz=quiz,
        podcast=podcast,
        document_context=context,
        document_id=document_id,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: AuthedUser = Depends(require_user)) -> ChatResponse:
    check_usage_limit(user.uid)

    context = request.document_context.strip()[:MAX_GEMINI_CONTEXT_CHARS]
    if not context:
        raise HTTPException(status_code=400, detail="Document context is missing. Please upload the PDF again.")

    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    system_instruction = (
        "You are a friendly study tutor. Answer questions using ONLY the uploaded document below. "
        "If a question cannot be answered from the document, reply: "
        "'Please ask a question related to the uploaded PDF.' Keep answers concise and clear.\n\n"
        f"File name: {request.file_name}\n\n"
        "Document content:\n\n"
        f"{context}"
    )

    contents: list[dict[str, Any]] = []
    for turn in request.history[-20:]:
        role = "user" if turn.role == "user" else "model"
        text = turn.text.strip()
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": question}]})

    answer = await call_gemini(system_instruction, contents, json_response=False)
    increment_usage(user.uid)
    return ChatResponse(answer=answer.strip())


@app.get("/api/documents/{doc_id}/chat", response_model=ChatLogResponse)
async def get_chat_log(doc_id: str, user: AuthedUser = Depends(require_user)) -> ChatLogResponse:
    # Returns the saved tutor conversation for this document so it can be
    # restored on the next visit. Empty when nothing has been saved yet.
    db = get_firestore_client()
    if db is None:
        return ChatLogResponse(messages=[])
    snapshot = _chat_log_ref(db, user.uid, doc_id).get()
    if not snapshot.exists:
        return ChatLogResponse(messages=[])
    data = snapshot.to_dict() or {}
    return ChatLogResponse(messages=[ChatMessage(**m) for m in data.get("messages", [])])


@app.put("/api/documents/{doc_id}/chat", response_model=ChatLogResponse)
async def save_chat_log(
    doc_id: str, request: ChatLogRequest, user: AuthedUser = Depends(require_user)
) -> ChatLogResponse:
    # Persisting chat is storage only — no paid API call, so it doesn't touch
    # the usage limit. Keep only the most recent messages, each text bounded,
    # so the stored transcript stays well under Firestore's 1 MiB cap.
    messages = [
        ChatMessage(role=m.role, text=truncate_utf8(m.text, MAX_STORED_CHAT_TEXT_BYTES))
        for m in request.messages[-MAX_STORED_CHAT_MESSAGES:]
    ]
    db = get_firestore_client()
    if db is not None:
        _chat_log_ref(db, user.uid, doc_id).set({"messages": [m.model_dump() for m in messages]})
    return ChatLogResponse(messages=messages)


@app.get("/api/documents/{doc_id}/quiz/attempts", response_model=QuizAttemptListResponse)
async def get_quiz_attempts(doc_id: str, user: AuthedUser = Depends(require_user)) -> QuizAttemptListResponse:
    return QuizAttemptListResponse(attempts=list_quiz_attempts(user.uid, doc_id))


@app.post("/api/documents/{doc_id}/quiz/attempts", response_model=QuizAttempt)
async def post_quiz_attempt(
    doc_id: str, request: QuizAttemptRequest, user: AuthedUser = Depends(require_user)
) -> QuizAttempt:
    if len(request.answers) != len(request.questions):
        raise HTTPException(status_code=400, detail="answers must have one entry per question.")
    # Storage only — recording a past attempt doesn't call any paid API, so
    # it doesn't touch the usage limit.
    return save_quiz_attempt(user.uid, doc_id, request.questions, request.answers)


@app.post("/api/documents/{doc_id}/quiz/regenerate", response_model=QuizRegenerateResponse)
async def regenerate_quiz(doc_id: str, user: AuthedUser = Depends(require_user)) -> QuizRegenerateResponse:
    check_usage_limit(user.uid)

    doc_ref, data = _get_document_or_404(user.uid, doc_id)
    context = _require_document_context(data, "quiz")

    # Ask Gemini to avoid repeating the current quiz and recent attempts, so
    # "new questions" is actually a different set rather than a reshuffle.
    avoid = [str(item.get("q") or "").strip() for item in data.get("quiz") or []]
    avoid = [q for q in avoid if q]
    for attempt in list_quiz_attempts(user.uid, doc_id)[:5]:
        for q in attempt.questions:
            if q.q not in avoid:
                avoid.append(q.q)
    avoid = avoid[:MAX_AVOID_QUESTIONS]
    avoid_block = "\n".join(f"- {q}" for q in avoid) if avoid else "(none yet)"

    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        f"File name: {data.get('file_name', 'uploaded-document.pdf')}\n\n"
                        f"Questions already used (avoid repeating these or close variants):\n{avoid_block}\n\n"
                        "Document content:\n\n"
                        f"{context}"
                    )
                }
            ],
        }
    ]
    raw_text = await call_gemini(QUIZ_SYSTEM_INSTRUCTION, contents, json_response=True)
    quiz = parse_quiz_questions(parse_json_text(raw_text))
    if not quiz:
        raise HTTPException(status_code=502, detail="Gemini response did not include usable quiz questions.")

    doc_ref.update({"quiz": [q.model_dump() for q in quiz]})
    increment_usage(user.uid)
    return QuizRegenerateResponse(quiz=quiz)


def _get_document_or_404(uid: str, doc_id: str):
    db = get_firestore_client()
    doc_ref = db.collection("users").document(uid).collection("documents").document(doc_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc_ref, snapshot.to_dict() or {}


def _require_document_context(data: dict[str, Any], what: str) -> str:
    context = (data.get("document_context") or "").strip()[:MAX_GEMINI_CONTEXT_CHARS]
    if not context:
        raise HTTPException(
            status_code=400,
            detail=f"This document's text wasn't saved, so a new {what} can't be generated. Re-upload the PDF.",
        )
    return context


@app.post("/api/documents/{doc_id}/summary/regenerate", response_model=SummaryRegenerateResponse)
async def regenerate_summary(
    doc_id: str, request: SummaryRegenerateRequest, user: AuthedUser = Depends(require_user)
) -> SummaryRegenerateResponse:
    check_usage_limit(user.uid)

    doc_ref, data = _get_document_or_404(user.uid, doc_id)
    context = _require_document_context(data, "summary")

    length = request.length if request.length in SUMMARY_LENGTHS else "concise"
    focus = request.focus.strip()[:200]
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
    raw_text = await call_gemini(build_summary_system_instruction(length, focus), contents, json_response=True)
    summary = parse_summary_points(parse_json_text(raw_text).get("summary"))
    if not summary:
        raise HTTPException(status_code=502, detail="Gemini response did not include a usable summary.")

    doc_ref.update({"summary": summary})
    increment_usage(user.uid)
    return SummaryRegenerateResponse(summary=summary)


@app.post("/api/documents/{doc_id}/podcast/regenerate", response_model=PodcastRegenerateResponse)
async def regenerate_podcast(
    doc_id: str, request: PodcastRegenerateRequest, user: AuthedUser = Depends(require_user)
) -> PodcastRegenerateResponse:
    check_usage_limit(user.uid)

    doc_ref, data = _get_document_or_404(user.uid, doc_id)
    context = _require_document_context(data, "podcast script")

    style = request.style if request.style in PODCAST_STYLES else "conversation"
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

    # The new script's segments no longer line up with any cached audio
    # (different text at the same indices), so drop the stale cache rather
    # than risk mismatched audio playing over the new transcript.
    for audio_doc in doc_ref.collection("audio").stream():
        audio_doc.reference.delete()

    doc_ref.update({"podcast": podcast.model_dump()})
    increment_usage(user.uid)
    return PodcastRegenerateResponse(podcast=podcast)


@app.get("/api/podcast/audio-status/{doc_id}", response_model=AudioStatusResponse)
async def podcast_audio_status(
    doc_id: str, user: AuthedUser = Depends(require_user)
) -> AudioStatusResponse:
    # Lets the frontend restore the player after a reload: it reports which
    # segments already have saved audio so cached playback needs no new
    # ElevenLabs calls (and no usage-limit hits).
    return AudioStatusResponse(cached_segments=list_cached_segment_indices(user.uid, doc_id))


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


async def elevenlabs_tts(text: str, speaker: int) -> tuple[bytes, str]:
    """Generate one segment via ElevenLabs. Returns (mp3_bytes, mime)."""
    api_key = get_elevenlabs_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "ElevenLabs API key is not configured. Add ELEVENLABS_API_KEY in your Vercel project settings "
                "(Settings → Environment Variables) and redeploy, or set it in a local .env file, or set "
                "TTS_PROVIDER=gemini to use Gemini TTS instead."
            ),
        )

    voice_a, voice_b = await resolve_voice_ids(api_key)
    voice_id = voice_a if speaker == 0 else voice_b
    url = f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}"

    async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(
                url,
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": api_key},
                json={
                    "text": text,
                    "model_id": ELEVENLABS_MODEL,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach the ElevenLabs API: {exc}") from exc

    if response.status_code != 200:
        try:
            detail = response.json()["detail"]
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
        except Exception:
            message = response.text[:300]
        raise HTTPException(status_code=502, detail=f"ElevenLabs API error ({response.status_code}): {message}")

    return response.content, "audio/mpeg"


async def gemini_tts(text: str, speaker: int) -> tuple[bytes, str]:
    """Generate one segment via Gemini TTS. Returns (wav_bytes, mime)."""
    api_key = get_gemini_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Gemini API key is not configured. Add GEMINI_API_KEY in your Vercel project settings "
                "(Settings → Environment Variables) and redeploy, or set it in a local .env file."
            ),
        )

    voice = GEMINI_TTS_VOICE_A if speaker == 0 else GEMINI_TTS_VOICE_B
    url = f"{GEMINI_API_BASE}/models/{GEMINI_TTS_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }

    async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(url, headers={"x-goog-api-key": api_key}, json=body)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach the Gemini API: {exc}") from exc

    if response.status_code != 200:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = response.text[:500]
        raise HTTPException(status_code=502, detail=f"Gemini TTS error ({response.status_code}): {message}")

    data = response.json()
    try:
        part = data["candidates"][0]["content"]["parts"][0]
        inline = part.get("inlineData") or part.get("inline_data")
        pcm = base64.b64decode(inline["data"])
        mime = inline.get("mimeType") or inline.get("mime_type") or ""
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="Gemini TTS returned an unexpected response shape.")

    # mimeType looks like "audio/L16;codec=pcm;rate=24000" — pull the rate.
    match = re.search(r"rate=(\d+)", mime)
    sample_rate = int(match.group(1)) if match else 24000
    return pcm_to_wav(pcm, sample_rate), "audio/wav"


@app.post("/api/podcast/segment-audio")
async def podcast_segment_audio(
    request: SegmentAudioRequest, user: AuthedUser = Depends(require_user)
) -> Response:
    has_cache_key = request.document_id and request.segment_index is not None
    if has_cache_key:
        cached = get_cached_segment_audio(user.uid, request.document_id, request.segment_index)
        if cached:
            audio_bytes, mime = cached
            return Response(content=audio_bytes, media_type=mime)

    check_usage_limit(user.uid)

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Segment text must not be empty.")
    if len(text) > MAX_SEGMENT_TEXT_CHARS:
        raise HTTPException(status_code=400, detail="Segment text is too long for audio generation.")

    # Gemini TTS is the cheaper default; ElevenLabs stays available via
    # TTS_PROVIDER=elevenlabs.
    if TTS_PROVIDER == "elevenlabs":
        audio_bytes, mime = await elevenlabs_tts(text, request.speaker)
    else:
        audio_bytes, mime = await gemini_tts(text, request.speaker)

    if has_cache_key:
        save_segment_audio(user.uid, request.document_id, request.segment_index, audio_bytes, mime)

    increment_usage(user.uid)
    return Response(content=audio_bytes, media_type=mime)
