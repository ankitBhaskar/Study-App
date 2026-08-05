"""System-instruction builders shared by the combined study-analysis prompt
and the standalone per-section regenerate prompts, so regenerating (e.g. "New
script") always reads consistently with what the first generation produced."""

from __future__ import annotations

from .config import FLASHCARDS_PER_SET, MAX_PODCAST_SCRIPT_CHARS

PODCAST_STYLES = {"conversation", "solo", "interview"}
SUMMARY_LENGTHS = {"concise", "detailed"}

PODCAST_STYLE_GUIDANCE = {
    "conversation": (
        'Format: a natural two-host conversation. Invent two host names (e.g. "Maya" and "Theo") who '
        "banter naturally, ask each other questions, and build on what the other just said. Alternate "
        "speakers frequently so both hosts get airtime."
    ),
    "solo": (
        "Format: a single narrator speaking alone, like a solo explainer podcast. Invent one host name "
        'and use that same name as "speaker" for every segment. Write it as a flowing monologue that '
        "still sounds spoken, not read aloud — use rhetorical questions and asides to keep it engaging."
    ),
    "interview": (
        'Format: an interview. Invent two names: a "Host" who asks probing questions and a "Guest" '
        "presented as an expert on the material who answers in more depth. Have the Host ask short "
        "follow-up questions after the Guest's answers."
    ),
}

SUMMARY_LENGTH_GUIDANCE = {
    "concise": "Write 4 to 6 concise key-point strings covering the document.",
    "detailed": (
        "Write 8 to 12 detailed key-point strings covering the document, going deeper into mechanisms, "
        "numbers and examples than a brief overview would."
    ),
}


def _summary_instruction_line(length: str, focus: str) -> str:
    line = SUMMARY_LENGTH_GUIDANCE.get(length, SUMMARY_LENGTH_GUIDANCE["concise"])
    focus = focus.strip()
    if focus:
        line += (
            f' Focus specifically on this topic from the document: "{focus}" — '
            "skip parts of the document unrelated to it."
        )
    return line


def build_study_system_instruction(podcast_style: str, summary_length: str, summary_focus: str) -> str:
    summary_line = _summary_instruction_line(summary_length, summary_focus)
    podcast_line = PODCAST_STYLE_GUIDANCE.get(podcast_style, PODCAST_STYLE_GUIDANCE["conversation"])
    return f"""You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Create study material and return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{{
  "title": "short document title, e.g. chapter name",
  "summary": ["key-point strings covering the document"],
  "quiz": {{
    "questions": [
      {{
        "question": "string",
        "options": ["exactly 4 answer options"],
        "correctOptionIndex": 0,
        "explanation": "why the answer is correct",
        "topic": "short topic label"
      }}
    ]
  }},
  "podcastScript": {{
    "durationMinutes": 10,
    "hosts": ["name", ...],
    "segments": [
      {{"timestamp": "0:00", "speaker": "name", "line": "spoken line"}}
    ]
  }}
}}
Summary instructions: {summary_line}
Podcast instructions: {podcast_line} Create 8 to 12 podcast segments with timestamps spread between 0:00 and 9:30 in mm:ss format.
Keep the combined spoken text of all podcast segments under {MAX_PODCAST_SCRIPT_CHARS} characters total — write shorter, punchier lines rather than fewer segments.
Create 3 to 5 quiz questions. Everything must be grounded in the document content."""


def build_summary_system_instruction(length: str, focus: str) -> str:
    summary_line = _summary_instruction_line(length, focus)
    return f"""You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Generate a fresh summary of the document. Return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{{
  "summary": ["key-point strings covering the document"]
}}
{summary_line} Everything must be grounded in the document content."""


def build_podcast_system_instruction(style: str) -> str:
    podcast_line = PODCAST_STYLE_GUIDANCE.get(style, PODCAST_STYLE_GUIDANCE["conversation"])
    return f"""You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Generate a fresh podcast script grounded in the document. Return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{{
  "durationMinutes": 10,
  "hosts": ["name", ...],
  "segments": [
    {{"timestamp": "0:00", "speaker": "name", "line": "spoken line"}}
  ]
}}
{podcast_line} Create 8 to 12 segments with timestamps spread between 0:00 and 9:30 in mm:ss format. Everything must be grounded in the document content.
Keep the combined spoken text of all segments under {MAX_PODCAST_SCRIPT_CHARS} characters total — write shorter, punchier lines rather than fewer segments."""


QUIZ_SYSTEM_INSTRUCTION = """You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Generate a fresh set of 3 to 5 multiple-choice quiz questions grounded in the document. Return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{
  "questions": [
    {
      "question": "string",
      "options": ["exactly 4 answer options"],
      "correctOptionIndex": 0,
      "explanation": "why the answer is correct",
      "topic": "short topic label"
    }
  ]
}
Do not repeat any question with the same meaning as one listed under "Questions already used" below — write genuinely
different questions, ideally covering different parts of the document. Everything must be grounded in the document content."""


FLASHCARD_SYSTEM_INSTRUCTION = f"""You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Generate a fresh set of EXACTLY {FLASHCARDS_PER_SET} study flashcards grounded in the document. Return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{{
  "cards": [
    {{
      "front": "a key term, concept or short question (under 80 characters)",
      "back": "a concise definition or answer (under 240 characters)"
    }}
  ]
}}
Do not repeat any card with the same meaning as one listed under "Card fronts already used" below — write genuinely
different cards, ideally covering different parts of the document. Everything must be grounded in the document content."""
