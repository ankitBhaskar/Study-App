"""PDF text extraction, cleanup and chunking for the standalone /pdf/prepare
preview endpoint (the full analyze flow chunks internally via Gemini's own
large context instead)."""

from __future__ import annotations

import io
import re

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader

from .config import (
    ALLOWED_IMAGE_CONTENT_TYPES,
    ALLOWED_IMAGE_EXTENSIONS,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    GEMINI_MODEL,
    MAX_FILE_SIZE_BYTES,
    MAX_FILES_PER_UPLOAD,
    MAX_TOTAL_UPLOAD_BYTES,
)
from .models import ExtractedPdf, ExtractedSource, GeminiPayload, PdfChunk
from .prompt_safety import sanitize_label


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


def _guess_image_mime(lower_name: str) -> str:
    if lower_name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower_name.endswith(".png"):
        return "image/png"
    if lower_name.endswith(".webp"):
        return "image/webp"
    if lower_name.endswith(".heic"):
        return "image/heic"
    if lower_name.endswith(".heif"):
        return "image/heif"
    return "application/octet-stream"


async def read_uploads(files: list[UploadFile]) -> list[ExtractedSource]:
    """Validate and ingest a /api/pdf/analyze upload: any mix of PDFs and
    images, up to MAX_FILES_PER_UPLOAD files and MAX_TOTAL_UPLOAD_BYTES
    combined. PDFs are text-extracted here; images are kept as raw bytes for
    the caller to send to Gemini as inline parts — Gemini reads them
    directly, no OCR step needed."""
    if not files:
        raise HTTPException(status_code=400, detail="Please choose at least one file.")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"You can upload up to {MAX_FILES_PER_UPLOAD} files at a time.",
        )

    max_mb = MAX_TOTAL_UPLOAD_BYTES // (1024 * 1024)
    sources: list[ExtractedSource] = []
    total_bytes = 0

    for file in files:
        # File names are attacker-controlled free text that ends up stored
        # and re-interpolated into a prompt on every later chat/regenerate
        # call for this document — sanitize once, here, rather than at each
        # of those call sites.
        name = sanitize_label(file.filename, 200) or "uploaded-file"
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail=f'"{name}" is empty.')

        total_bytes += len(file_bytes)
        if total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"These files are too large together. Up to {max_mb} MB total is supported.",
            )

        content_type = (file.content_type or "").lower()
        lower_name = name.lower()
        is_pdf = content_type in {"application/pdf", "application/x-pdf"} or lower_name.endswith(".pdf")
        is_image = content_type in ALLOWED_IMAGE_CONTENT_TYPES or lower_name.endswith(ALLOWED_IMAGE_EXTENSIONS)

        if is_pdf:
            extracted = extract_pdf_text(file_bytes)
            if not extracted.text:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f'No readable text was found in "{name}". This may be a scanned PDF and may need '
                        "OCR before Gemini processing."
                    ),
                )
            sources.append(
                ExtractedSource(name=name, kind="pdf", page_count=extracted.page_count, text=extracted.text)
            )
        elif is_image:
            mime = content_type if content_type in ALLOWED_IMAGE_CONTENT_TYPES else _guess_image_mime(lower_name)
            sources.append(ExtractedSource(name=name, kind="image", page_count=1, image_bytes=file_bytes, mime=mime))
        else:
            raise HTTPException(
                status_code=400,
                detail=f'"{name}" isn\'t a supported file type. Upload PDFs or images (JPEG, PNG, WEBP, HEIC).',
            )

    return sources
