"""Quiz attempt history and quiz regeneration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user
from ..config import MAX_AVOID_QUESTIONS, MAX_QUIZ_ATTEMPT_QUESTIONS
from ..gemini_client import call_gemini, parse_json_text
from ..models import (
    AuthedUser,
    QuizAttempt,
    QuizAttemptListResponse,
    QuizAttemptRequest,
    QuizQuestion,
    QuizRegenerateResponse,
)
from ..prompt_safety import format_untrusted_list, frame_untrusted_document, sanitize_label
from ..storage.documents import _get_document_or_404, _require_document_context
from ..storage.quiz_attempts import list_quiz_attempts, save_quiz_attempt
from ..storage.usage import reserve_usage
from ..study_parsing import parse_quiz_questions
from ..study_prompts import QUIZ_SYSTEM_INSTRUCTION

router = APIRouter()


@router.get("/api/documents/{doc_id}/quiz/attempts", response_model=QuizAttemptListResponse)
async def get_quiz_attempts(doc_id: str, user: AuthedUser = Depends(require_user)) -> QuizAttemptListResponse:
    return QuizAttemptListResponse(attempts=list_quiz_attempts(user.uid, doc_id))


@router.post("/api/documents/{doc_id}/quiz/attempts", response_model=QuizAttempt)
async def post_quiz_attempt(
    doc_id: str, request: QuizAttemptRequest, user: AuthedUser = Depends(require_user)
) -> QuizAttempt:
    if len(request.answers) != len(request.questions):
        raise HTTPException(status_code=400, detail="answers must have one entry per question.")
    if len(request.questions) > MAX_QUIZ_ATTEMPT_QUESTIONS:
        raise HTTPException(
            status_code=400, detail=f"A quiz attempt can have at most {MAX_QUIZ_ATTEMPT_QUESTIONS} questions."
        )
    # The question text here is whatever the client sends, and it's stored
    # and later fed back into the regenerate prompt's avoid-list — so bound
    # it before storage (sanitized again at the point of use).
    questions = [
        QuizQuestion(
            q=q.q[:1000],
            options=[o[:500] for o in q.options[:10]],
            answer=q.answer,
            topic=q.topic[:100],
            explanation=q.explanation[:2000],
        )
        for q in request.questions
    ]
    # Storage only — recording a past attempt doesn't call any paid API, so
    # it doesn't touch the usage limit.
    return save_quiz_attempt(user.uid, doc_id, questions, request.answers)


@router.post("/api/documents/{doc_id}/quiz/regenerate", response_model=QuizRegenerateResponse)
async def regenerate_quiz(doc_id: str, user: AuthedUser = Depends(require_user)) -> QuizRegenerateResponse:
    reserve_usage(user.uid)

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
    avoid_block = format_untrusted_list(avoid[:MAX_AVOID_QUESTIONS])
    file_name = sanitize_label(data.get("file_name"), 200) or "uploaded-document.pdf"

    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        f"File name: {file_name}\n\n"
                        f"Questions already used (avoid repeating these or close variants):\n{avoid_block}\n\n"
                        f"{frame_untrusted_document(context)}"
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
    return QuizRegenerateResponse(quiz=quiz)
