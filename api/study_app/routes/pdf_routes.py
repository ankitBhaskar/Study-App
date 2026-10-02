"""PDF upload endpoints: chunk preview and the full Gemini analysis."""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile

from ..auth import require_user
from ..config import MAX_GEMINI_CONTEXT_CHARS, MAX_STORED_CONTEXT_BYTES
from ..firebase_client import get_firestore_client
from ..gemini_client import call_gemini, parse_json_text
from ..models import AuthedUser, PdfProcessingResponse, StudyAnalysisResponse
from ..pdf_processing import build_gemini_payload, chunk_text, read_pdf_upload, read_uploads
from ..prompt_safety import frame_untrusted_document
from ..storage.flashcard_sets import save_flashcard_set
from ..storage.usage import reserve_usage
from ..study_parsing import normalise_study_content, parse_image_notes
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
    # Any mix of PDFs and images, from either the web or mobile client — both
    # send the same multipart field name, repeated once per file.
    files: list[UploadFile] = File(...),
    # Optional generation options — same choices exposed as "New questions" /
    # "New script" regeneration after the fact, but selectable up front too.
    podcast_style: str = Form("conversation"),
    summary_length: str = Form("concise"),
    summary_focus: str = Form(""),
    user: AuthedUser = Depends(require_user),
) -> StudyAnalysisResponse:
    reserve_usage(user.uid)

    sources = await read_uploads(files)
    file_names = [s.name for s in sources]
    file_name = file_names[0] if len(file_names) == 1 else f"{file_names[0]} +{len(file_names) - 1} more"

    podcast_style = podcast_style if podcast_style in PODCAST_STYLES else "conversation"
    summary_length = summary_length if summary_length in SUMMARY_LENGTHS else "concise"
    summary_focus = summary_focus.strip()[:200]

    pdf_text = "\n\n".join(f"=== Source: {s.name} ===\n{s.text}" for s in sources if s.kind == "pdf")
    context = pdf_text[:MAX_GEMINI_CONTEXT_CHARS]
    images = [s for s in sources if s.kind == "image"]

    # Gemini reads images directly as inline parts — no OCR step. The lead
    # text part carries the file names and any PDF text; one text label plus
    # one inlineData part follows per image so Gemini can tie its imageNotes
    # entries back to a source name.
    parts: list[dict[str, Any]] = [
        {
            "text": (
                f"Source file names: {', '.join(file_names)}\n\n"
                + (f"{frame_untrusted_document(context)}\n\n" if context else "")
                + (f"{len(images)} image source(s) follow as attachments." if images else "")
            )
        }
    ]
    for image in images:
        parts.append({"text": f"=== Source: {image.name} (image) ==="})
        parts.append(
            {
                "inlineData": {
                    "mimeType": image.mime,
                    "data": base64.b64encode(image.image_bytes).decode("ascii"),
                }
            }
        )

    contents = [{"role": "user", "parts": parts}]

    system_instruction = build_study_system_instruction(
        podcast_style, summary_length, summary_focus, has_images=bool(images)
    )
    raw_text = await call_gemini(system_instruction, contents, json_response=True)
    raw = parse_json_text(raw_text)
    title, summary, quiz, podcast, flashcards = normalise_study_content(raw, file_name)

    # Raw image bytes are never stored or re-sent — Gemini's own transcription
    # of each image (imageNotes) is folded into the text context instead, so
    # tutor chat and regenerate-* (which only ever see stored text) still have
    # something to ground image content in.
    image_notes = parse_image_notes(raw) if images else {}
    context_sections = [pdf_text] if pdf_text else []
    for image in images:
        note = image_notes.get(image.name, "").strip()
        if note:
            context_sections.append(f"=== Source: {image.name} (image) ===\n{note}")
    full_context = "\n\n".join(context_sections)[:MAX_GEMINI_CONTEXT_CHARS]

    page_count = sum(s.page_count for s in sources)

    db = get_firestore_client()
    document_id = None
    if db is not None:
        # The uploaded files themselves are never stored — only the combined
        # text (truncated to fit Firestore's 1 MiB document cap) and the
        # derived study data, so Tutor chat keeps working on history-reopened
        # docs.
        _, doc_ref = db.collection("users").document(user.uid).collection("documents").add(
            {
                "title": title,
                "file_name": file_name,
                "file_names": file_names,
                "summary": summary,
                "quiz": [q.model_dump() for q in quiz],
                "podcast": podcast.model_dump(),
                # Every generated style version is kept so switching styles
                # later loads from storage instead of re-calling Gemini.
                # audio_ns names the audio-cache namespace for this version.
                "podcast_style": podcast_style,
                "podcast_versions": {podcast_style: {**podcast.model_dump(), "audio_ns": podcast_style}},
                "document_context": truncate_utf8(full_context, MAX_STORED_CONTEXT_BYTES),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        document_id = doc_ref.id
        # Loads by default on the Flashcards tab, same as summary/quiz/podcast
        # — no separate "Generate flashcards" click needed for the first set.
        if flashcards:
            save_flashcard_set(user.uid, document_id, flashcards)

    return StudyAnalysisResponse(
        file_name=file_name,
        file_names=file_names,
        page_count=page_count,
        title=title,
        summary=summary,
        quiz=quiz,
        podcast=podcast,
        document_context=full_context,
        document_id=document_id,
        podcast_style=podcast_style,
        saved_styles=[podcast_style],
    )
