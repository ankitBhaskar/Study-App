"""Flashcard set history and regeneration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user
from ..config import MAX_AVOID_CARDS
from ..gemini_client import call_gemini, parse_json_text
from ..models import AuthedUser, FlashcardRegenerateResponse, FlashcardSetListResponse
from ..prompt_safety import frame_untrusted_document, sanitize_label
from ..storage.documents import _get_document_or_404, _require_document_context
from ..storage.flashcard_sets import list_flashcard_sets, save_flashcard_set
from ..storage.usage import reserve_usage
from ..study_parsing import parse_flashcards
from ..study_prompts import FLASHCARD_SYSTEM_INSTRUCTION

router = APIRouter()


@router.get("/api/documents/{doc_id}/flashcards", response_model=FlashcardSetListResponse)
async def get_flashcard_sets(doc_id: str, user: AuthedUser = Depends(require_user)) -> FlashcardSetListResponse:
    # Storage only — every previously generated set, newest first.
    return FlashcardSetListResponse(sets=list_flashcard_sets(user.uid, doc_id))


@router.post("/api/documents/{doc_id}/flashcards/regenerate", response_model=FlashcardRegenerateResponse)
async def regenerate_flashcards(doc_id: str, user: AuthedUser = Depends(require_user)) -> FlashcardRegenerateResponse:
    reserve_usage(user.uid)

    _, data = _get_document_or_404(user.uid, doc_id)
    context = _require_document_context(data, "flashcard set")

    # Ask Gemini to avoid repeating recent sets' fronts, so a new set covers
    # genuinely new ground. Old sets are NOT deleted — they stay listed.
    avoid: list[str] = []
    for card_set in list_flashcard_sets(user.uid, doc_id)[:5]:
        for card in card_set.cards:
            if card.front not in avoid:
                avoid.append(card.front)
    avoid = avoid[:MAX_AVOID_CARDS]
    avoid_block = "\n".join(f"- {front}" for front in avoid) if avoid else "(none yet)"
    file_name = sanitize_label(data.get("file_name"), 200) or "uploaded-document.pdf"

    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        f"File name: {file_name}\n\n"
                        f"Card fronts already used (avoid repeating these or close variants):\n{avoid_block}\n\n"
                        f"{frame_untrusted_document(context)}"
                    )
                }
            ],
        }
    ]
    raw_text = await call_gemini(FLASHCARD_SYSTEM_INSTRUCTION, contents, json_response=True)
    cards = parse_flashcards(parse_json_text(raw_text))
    if not cards:
        raise HTTPException(status_code=502, detail="Gemini response did not include usable flashcards.")

    card_set = save_flashcard_set(user.uid, doc_id, cards)
    return FlashcardRegenerateResponse(set=card_set)
