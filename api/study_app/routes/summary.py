"""Summary regeneration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user
from ..gemini_client import call_gemini, parse_json_text
from ..models import AuthedUser, SummaryRegenerateRequest, SummaryRegenerateResponse
from ..prompt_safety import frame_untrusted_document, sanitize_label
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
    # Further hardened inside build_summary_system_instruction() ->
    # _summary_instruction_line() via sanitize_label() — this is just the
    # existing input-bounding step at the API boundary.
    focus = request.focus.strip()[:200]
    file_name = sanitize_label(data.get("file_name"), 200) or "uploaded-document.pdf"
    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        f"File name: {file_name}\n\n"
                        f"{frame_untrusted_document(context)}"
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
