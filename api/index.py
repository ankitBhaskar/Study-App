from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import firebase_admin
import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
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
MAX_GEMINI_CONTEXT_CHARS = 200_000
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
MAX_SEGMENT_TEXT_CHARS = 1_000
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY")
# Local dev/testing against the Firebase Local Emulator Suite needs no real
# service account — the emulator env vars are enough to talk to it.
USING_FIREBASE_EMULATOR = bool(os.getenv("FIRESTORE_EMULATOR_HOST") or os.getenv("FIREBASE_AUTH_EMULATOR_HOST"))
# Shared daily cap across document analysis, tutor chat and podcast audio —
# the three actions that call a paid API. One counter keeps this simple;
# split it into separate counters later if different limits are needed.
DAILY_USAGE_LIMIT = int(os.getenv("DAILY_USAGE_LIMIT", "5"))
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


class SegmentAudioRequest(BaseModel):
    text: str
    speaker: int = 0


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


STUDY_SYSTEM_INSTRUCTION = """You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Create study material and return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{
  "title": "short document title, e.g. chapter name",
  "summary": ["4 to 6 key-point strings covering the document"],
  "quiz": {
    "questions": [
      {
        "question": "string",
        "options": ["exactly 4 answer options"],
        "correctOptionIndex": 0,
        "explanation": "why the answer is correct",
        "topic": "short topic label"
      }
    ]
  },
  "podcastScript": {
    "title": "episode title",
    "durationMinutes": 10,
    "hosts": ["Maya", "Theo"],
    "segments": [
      {"timestamp": "0:00", "speaker": "Maya", "line": "spoken line"}
    ]
  }
}
Create 3 to 5 quiz questions. Create 8 to 12 podcast segments as a natural two-host conversation walking through the document,
with timestamps spread between 0:00 and 9:30 in mm:ss format. Everything must be grounded in the document content."""


def normalise_study_content(raw: dict[str, Any], file_name: str) -> tuple[str, list[str], list[QuizQuestion], Podcast]:
    title = str(raw.get("title") or file_name)

    summary_raw = raw.get("summary")
    if isinstance(summary_raw, dict):
        summary_raw = summary_raw.get("detailedSummary") or [summary_raw.get("shortSummary", "")]
    summary = [str(point) for point in summary_raw or [] if str(point).strip()]
    if not summary:
        raise HTTPException(status_code=502, detail="Gemini response did not include a usable summary.")

    quiz_raw = raw.get("quiz") or {}
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
    if not quiz:
        raise HTTPException(status_code=502, detail="Gemini response did not include usable quiz questions.")

    podcast_raw = raw.get("podcastScript") or {}
    hosts = [str(host) for host in podcast_raw.get("hosts") or []] or ["Maya", "Theo"]
    segments: list[PodcastSegment] = []
    for seg in podcast_raw.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        line = str(seg.get("line") or "").strip()
        if not line:
            continue
        timestamp = str(seg.get("timestamp") or seg.get("t") or "0:00")
        if not re.fullmatch(r"\d{1,2}:\d{2}", timestamp):
            timestamp = "0:00"
        segments.append(PodcastSegment(t=timestamp, who=str(seg.get("speaker") or seg.get("who") or hosts[0]), line=line))
    if not segments:
        raise HTTPException(status_code=502, detail="Gemini response did not include a usable podcast script.")

    try:
        duration_minutes = int(podcast_raw.get("durationMinutes") or 10)
    except (TypeError, ValueError):
        duration_minutes = 10
    podcast = Podcast(duration=f"{duration_minutes}:00", hosts=hosts[:2], transcript=segments)

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


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, user: AuthedUser = Depends(require_user)) -> dict[str, str]:
    db = get_firestore_client()
    db.collection("users").document(user.uid).collection("documents").document(doc_id).delete()
    return {"status": "deleted"}


@app.delete("/api/documents")
async def clear_documents(user: AuthedUser = Depends(require_user)) -> dict[str, str]:
    db = get_firestore_client()
    docs_ref = db.collection("users").document(user.uid).collection("documents")
    for doc in docs_ref.stream():
        doc.reference.delete()
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
async def analyze_pdf(file: UploadFile = File(...), user: AuthedUser = Depends(require_user)) -> StudyAnalysisResponse:
    check_usage_limit(user.uid)

    extracted = await read_pdf_upload(file)
    file_name = file.filename or "uploaded-document.pdf"
    context = extracted.text[:MAX_GEMINI_CONTEXT_CHARS]

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

    raw_text = await call_gemini(STUDY_SYSTEM_INSTRUCTION, contents, json_response=True)
    raw = parse_json_text(raw_text)
    title, summary, quiz, podcast = normalise_study_content(raw, file_name)

    increment_usage(user.uid)
    db = get_firestore_client()
    if db is not None:
        # Only the derived study data is persisted — never the PDF or the
        # extracted document text — per the "data, not the document" design.
        db.collection("users").document(user.uid).collection("documents").add(
            {
                "title": title,
                "file_name": file_name,
                "summary": summary,
                "quiz": [q.model_dump() for q in quiz],
                "podcast": podcast.model_dump(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    return StudyAnalysisResponse(
        file_name=file_name,
        page_count=extracted.page_count,
        title=title,
        summary=summary,
        quiz=quiz,
        podcast=podcast,
        document_context=context,
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


@app.post("/api/podcast/segment-audio")
async def podcast_segment_audio(
    request: SegmentAudioRequest, user: AuthedUser = Depends(require_user)
) -> Response:
    check_usage_limit(user.uid)

    api_key = get_elevenlabs_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "ElevenLabs API key is not configured. Add ELEVENLABS_API_KEY in your Vercel project settings "
                "(Settings → Environment Variables) and redeploy, or set it in a local .env file."
            ),
        )

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Segment text must not be empty.")
    if len(text) > MAX_SEGMENT_TEXT_CHARS:
        raise HTTPException(status_code=400, detail="Segment text is too long for audio generation.")

    voice_a, voice_b = await resolve_voice_ids(api_key)
    voice_id = voice_a if request.speaker == 0 else voice_b
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

    increment_usage(user.uid)
    return Response(content=response.content, media_type="audio/mpeg")
