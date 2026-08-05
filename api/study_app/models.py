"""Pydantic request/response schemas and the plain PDF-extraction data type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


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
    # Which podcast style the returned script is in, and which styles have a
    # saved version — lets the UI mark those chips as load-from-storage
    # instead of showing them as fresh AI generations.
    podcast_style: str = "conversation"
    saved_styles: list[str] = []


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


class Flashcard(BaseModel):
    front: str
    back: str


class FlashcardSet(BaseModel):
    id: str
    cards: list[Flashcard]
    created_at: str


class FlashcardSetListResponse(BaseModel):
    sets: list[FlashcardSet]


class FlashcardRegenerateResponse(BaseModel):
    set: FlashcardSet


class SummaryRegenerateRequest(BaseModel):
    length: str = "concise"
    focus: str = ""


class SummaryRegenerateResponse(BaseModel):
    summary: list[str]


class PodcastRegenerateRequest(BaseModel):
    style: str = "conversation"


class PodcastRegenerateResponse(BaseModel):
    podcast: Podcast
    podcast_style: str = "conversation"
    saved_styles: list[str] = []
    # True when the requested style already had a saved version and it was
    # loaded from storage — no Gemini call, no usage charged.
    reused: bool = False


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
    # True when the active style has a single continuous whole-episode track
    # cached (the "full" sentinel document) — the preferred playback form.
    episode_cached: bool = False


class EpisodeAudioRequest(BaseModel):
    document_id: str


class AuthedUser(BaseModel):
    uid: str
    email: str | None = None


class FeedbackRequest(BaseModel):
    rating: int
    comment: str = ""
    # Which screen the feedback was given from, e.g. "summary"/"podcast" —
    # purely contextual, never trusted for anything beyond display.
    context: str = ""


class FeedbackResponse(BaseModel):
    ok: bool
    emailed: bool


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
    podcast_style: str = "conversation"
    saved_styles: list[str] = []


class DocumentListResponse(BaseModel):
    documents: list[DocumentRecord]
