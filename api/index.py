from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
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
# Premade ElevenLabs voices: Rachel (host A) and Adam (host B).
ELEVENLABS_VOICE_HOST_A = os.getenv("ELEVENLABS_VOICE_HOST_A", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_VOICE_HOST_B = os.getenv("ELEVENLABS_VOICE_HOST_B", "pNInz6obpgDQGcFmaJgB")
ELEVENLABS_TIMEOUT_SECONDS = 55.0
MAX_SEGMENT_TEXT_CHARS = 1_000

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


def get_gemini_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def get_elevenlabs_api_key() -> str | None:
    return os.getenv("ELEVENLABS_API_KEY")


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
    }


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
async def analyze_pdf(file: UploadFile = File(...)) -> StudyAnalysisResponse:
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
async def chat(request: ChatRequest) -> ChatResponse:
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
    return ChatResponse(answer=answer.strip())


@app.post("/api/podcast/segment-audio")
async def podcast_segment_audio(request: SegmentAudioRequest) -> Response:
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

    voice_id = ELEVENLABS_VOICE_HOST_A if request.speaker == 0 else ELEVENLABS_VOICE_HOST_B
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

    return Response(content=response.content, media_type="audio/mpeg")
