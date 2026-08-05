"""PDF upload endpoints: chunk preview and the full Gemini analysis."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, UploadFile

from ..auth import require_user
from ..config import MAX_GEMINI_CONTEXT_CHARS, MAX_STORED_CONTEXT_BYTES
from ..firebase_client import get_firestore_client
from ..gemini_client import call_gemini, parse_json_text
from ..models import AuthedUser, PdfProcessingResponse, StudyAnalysisResponse
from ..pdf_processing import build_gemini_payload, chunk_text, read_pdf_upload
from ..storage.usage import reserve_usage
from ..study_parsing import normalise_study_content
from ..study_prompts import PODCAST_STYLES, SUMMARY_LENGTHS, build_study_system_instruction
from ..utils import truncate_utf8

router = APIRouter()


@router.post("/api/pdf/prepare", response_model=PdfProcessingResponse)
async def prepare_pdf(
    file: UploadFile = File(...),
    # Requires auth even though it never calls Gemini: PDF parsing is CPU/
    # memory work bounded only by maxDuration, so leaving it open let anyone
    # burn serverless compute with crafted 4 MB PDFs. The app itself uploads
    # to the authed /api/pdf/analyze, so gating this changes no real flow.
    user: AuthedUser = Depends(require_user),
) -> PdfProcessingResponse:
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


@router.post("/api/pdf/analyze", response_model=StudyAnalysisResponse)
async def analyze_pdf(
    file: UploadFile = File(...),
    # Optional generation options — same choices exposed as "New questions" /
    # "New script" regeneration after the fact, but selectable up front too.
    podcast_style: str = Form("conversation"),
    summary_length: str = Form("concise"),
    summary_focus: str = Form(""),
    user: AuthedUser = Depends(require_user),
) -> StudyAnalysisResponse:
    reserve_usage(user.uid)

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
                # Every generated style version is kept so switching styles
                # later loads from storage instead of re-calling Gemini.
                # audio_ns names the audio-cache namespace for this version.
                "podcast_style": podcast_style,
                "podcast_versions": {podcast_style: {**podcast.model_dump(), "audio_ns": podcast_style}},
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
        podcast_style=podcast_style,
        saved_styles=[podcast_style],
    )
