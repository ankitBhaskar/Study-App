"""Best-effort outbound notifications (currently just feedback emails)."""

from __future__ import annotations

import httpx

from .config import FEEDBACK_EMAIL_FROM, FEEDBACK_EMAIL_TO, RESEND_API_KEY


async def send_feedback_email(rating: int, comment: str, context: str, from_email: str | None) -> bool:
    """Best-effort email notification for a feedback submission via Resend
    (https://resend.com — a single HTTP call, no SMTP setup). Returns False
    (never raises) if RESEND_API_KEY/FEEDBACK_EMAIL_TO aren't configured or
    the request fails — feedback is always saved to Firestore regardless, so
    a misconfigured or down email service never blocks the submission."""
    if not RESEND_API_KEY or not FEEDBACK_EMAIL_TO:
        return False

    stars = "★" * rating + "☆" * (5 - rating)
    lines = [
        f"Rating: {stars} ({rating}/5)",
        f"From: {from_email or 'unknown user'}",
    ]
    if context:
        lines.append(f"Screen: {context}")
    lines.append("")
    lines.append(comment or "(no comment)")
    text_body = "\n".join(lines)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={
                    "from": FEEDBACK_EMAIL_FROM,
                    "to": [FEEDBACK_EMAIL_TO],
                    "subject": f"Syrora feedback: {stars} ({rating}/5)",
                    "text": text_body,
                },
            )
        return response.status_code < 300
    except httpx.HTTPError:
        return False
