"""Parsing/validation of Gemini's study-content JSON into typed models."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from .config import FLASHCARDS_PER_SET, MAX_PODCAST_SCRIPT_CHARS
from .models import Flashcard, Podcast, PodcastSegment, QuizQuestion


def parse_flashcards(raw: Any) -> list[Flashcard] | None:
    cards_raw = raw.get("cards") if isinstance(raw, dict) else raw
    cards: list[Flashcard] = []
    for card in cards_raw or []:
        if not isinstance(card, dict):
            continue
        front = str(card.get("front") or "").strip()[:120]
        back = str(card.get("back") or "").strip()[:400]
        if front and back:
            cards.append(Flashcard(front=front, back=back))
        if len(cards) == FLASHCARDS_PER_SET:
            break
    # A short set is useless as a study aid; treat it as a bad completion.
    return cards if len(cards) >= 3 else None


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
