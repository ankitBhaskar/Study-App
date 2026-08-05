"""Summary regeneration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user
from ..gemini_client import call_gemini, parse_json_text
from ..models import AuthedUser, SummaryRegenerateRequest, SummaryRegenerateResponse
from ..storage.documents import _get_document_or_404, _require_document_context
from ..storage.usage import reserve_usage
from ..study_parsing import parse_summary_points
from ..study_prompts import SUMMARY_LENGTHS, build_summary_system_instruction

router = APIRouter()


@router.post("/api/documents/{doc_id}/summary/regenerate", response_model=SummaryRegenerateResponse)
async def regenerate_summary(
    doc_id: str, request: SummaryRegenerateRequest, user: AuthedUser = Depends(require_user)
) -> SummaryRegenerateResponse:
    reserve_usage(user.uid)

    doc_ref, data = _get_document_or_404(user.uid, doc_id)
    context = _require_document_context(data, "summary")

    length = request.length if request.length in SUMMARY_LENGTHS else "concise"
    focus = request.focus.strip()[:200]
    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        f"File name: {data.get('file_name', 'uploaded-document.pdf')}\n\n"
                        "Document content:\n\n"
                        f"{context}"
                    )
                }
            ],
        }
    ]
    raw_text = await call_gemini(build_summary_system_instruction(length, focus), contents, json_response=True)
    summary = parse_summary_points(parse_json_text(raw_text).get("summary"))
    if not summary:
        raise HTTPException(status_code=502, detail="Gemini response did not include a usable summary.")

    doc_ref.update({"summary": summary})
    return SummaryRegenerateResponse(summary=summary)
