from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pypdf import PdfReader

APP_NAME = "Study App PDF Processing API"
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
DEFAULT_CHUNK_SIZE = 6_000
DEFAULT_CHUNK_OVERLAP = 600

app = FastAPI(
    title=APP_NAME,
    version="0.1.0",
    description="Extracts, cleans and chunks PDF text so it is ready to pass into Gemini or another LLM.",
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
        model="gemini-1.5-flash",
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": APP_NAME}


@app.post("/api/pdf/prepare", response_model=PdfProcessingResponse)
async def prepare_pdf(file: UploadFile = File(...)) -> PdfProcessingResponse:
    if file.content_type not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty.")
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="PDF is too large. Maximum supported size is 20 MB.")

    extracted = extract_pdf_text(file_bytes)
    if not extracted.text:
        raise HTTPException(
            status_code=422,
            detail="No readable text was found. This may be a scanned PDF and may need OCR before Gemini processing.",
        )

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
