"""Environment configuration and tunable limits, loaded once at import time."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

APP_NAME = "Study App API"
# Vercel serverless functions reject request bodies over ~4.5 MB, so the
# upload limit must stay below that even though Gemini could handle more.
# Used by the single-file /api/pdf/prepare preview endpoint.
MAX_FILE_SIZE_BYTES = 4 * 1024 * 1024
# /api/pdf/analyze accepts several PDFs/images in one request, but they all
# share the same multipart body, so this caps their COMBINED size rather
# than each file individually — the Vercel body limit above applies to the
# whole request either way.
MAX_FILES_PER_UPLOAD = 5
MAX_TOTAL_UPLOAD_BYTES = 4 * 1024 * 1024
ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")
DEFAULT_CHUNK_SIZE = 6_000
DEFAULT_CHUNK_OVERLAP = 600
# A 4 MB text-based PDF rarely extracts to more than this; ~400k chars is
# roughly 100k tokens, comfortably inside gemini-2.5-flash's 1M context.
MAX_GEMINI_CONTEXT_CHARS = 400_000
GEMINI_API_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_SECONDS = 55.0
ELEVENLABS_API_BASE = os.getenv("ELEVENLABS_API_BASE", "https://api.elevenlabs.io/v1")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
# Optional explicit overrides. Left unset, the two host voices are resolved
# at runtime from GET /v1/voices — free-tier ElevenLabs accounts get a 402
# calling the text-to-speech endpoint with a "voice library" ID that isn't
# already in their own account, so hardcoding well-known IDs (e.g. the
# premade Rachel/Adam voices) breaks for exactly those accounts. Reading the
# account's own voice list guarantees whatever we pick is actually usable.
ELEVENLABS_VOICE_HOST_A = os.getenv("ELEVENLABS_VOICE_HOST_A")
ELEVENLABS_VOICE_HOST_B = os.getenv("ELEVENLABS_VOICE_HOST_B")
ELEVENLABS_TIMEOUT_SECONDS = 55.0
# Which text-to-speech backend the podcast audio uses: "google" (Cloud
# Text-to-Speech, default — synthesizes a whole 4,500-char episode in ONE
# fast call), "gemini" (Gemini TTS, slower LLM-based synthesis in batches)
# or "elevenlabs". All three code paths are kept intact; only the selected
# one runs.
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "google").strip().lower()
# Google Cloud Text-to-Speech (texttospeech.googleapis.com). Needs the
# Cloud TTS API enabled on the key's Google Cloud project; the key falls
# back to GEMINI_API_KEY when GOOGLE_TTS_API_KEY isn't set. Neural2 voices
# cost $16/1M chars (WaveNet $4/1M), both with ~1M chars/month free. One
# voice narrates the whole episode (these voices have no multi-speaker
# mode).
GOOGLE_TTS_API_BASE = os.getenv("GOOGLE_TTS_API_BASE", "https://texttospeech.googleapis.com/v1")
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE", "en-US-Neural2-F")
GOOGLE_TTS_TIMEOUT_SECONDS = float(os.getenv("GOOGLE_TTS_TIMEOUT_SECONDS", "55"))
# Cloud TTS rejects requests over 5,000 input bytes; scripts are capped at
# 4,500 chars but multi-byte punctuation could push past, so episodes are
# packed into as few synthesize calls as fit under this byte budget
# (normally exactly one).
GOOGLE_TTS_MAX_INPUT_BYTES = 4_800
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
# Two prebuilt Gemini voices for the two hosts. Full list in Gemini's TTS
# docs (Kore, Puck, Charon, Fenrir, Aoede, Leda, Orus, Zephyr, …).
GEMINI_TTS_VOICE_A = os.getenv("GEMINI_TTS_VOICE_A", "Kore")
GEMINI_TTS_VOICE_B = os.getenv("GEMINI_TTS_VOICE_B", "Puck")
# Synthesizing a multi-segment batch produces minutes of audio and takes far
# longer than a text completion, so TTS gets its own timeout instead of
# GEMINI_TIMEOUT_SECONDS. Must stay under vercel.json's maxDuration.
GEMINI_TTS_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TTS_TIMEOUT_SECONDS", "280"))
# A full 4,500-char script is ~5 minutes of audio — too long to synthesize
# inside one serverless request. Consecutive segments are grouped into
# batches of at most this many spoken characters and each batch is one
# Gemini call, so a max-length script needs 2 calls (still within the free
# tier's 3 requests/minute) and each call finishes well inside maxDuration.
GEMINI_TTS_BATCH_CHARS = int(os.getenv("GEMINI_TTS_BATCH_CHARS", "2250"))
# Firestore caps a document at 1 MiB. Cached audio larger than this raw-byte
# threshold is split across sibling chunk documents (base64 inflates ~4/3,
# so this leaves headroom under the cap per document).
MAX_CACHED_AUDIO_BYTES = 740_000
MAX_SEGMENT_TEXT_CHARS = 1_000
# Keeps each episode's total spoken text (all segment lines combined) short
# enough to stay cheap and fast to synthesize regardless of TTS provider.
# Enforced both in the prompt (so Gemini writes a shorter script) and in
# parse_podcast_script() (so a script that ignores the prompt still gets
# capped rather than trusted as-is).
MAX_PODCAST_SCRIPT_CHARS = 4_500
# Bound the persisted tutor transcript so it can't grow past Firestore's
# 1 MiB document cap: keep the most recent messages, each text truncated.
MAX_STORED_CHAT_MESSAGES = 60
MAX_STORED_CHAT_TEXT_BYTES = 10_000
# Firestore caps a document at 1 MiB (1,048,576 bytes) including every field;
# 900 KB of text leaves ~120 KB of headroom for the study data stored with it.
MAX_STORED_CONTEXT_BYTES = 900_000
# Keep only the most recent quiz attempts per document, and only look at a
# bounded number of past questions when asking Gemini to avoid repeats.
MAX_QUIZ_ATTEMPTS = 20
MAX_AVOID_QUESTIONS = 30
# Flashcards: every set is 6 cards; generating a new set keeps the old ones
# (bounded per document) and asks Gemini to avoid repeating recent fronts.
FLASHCARDS_PER_SET = 6
MAX_FLASHCARD_SETS = 10
MAX_AVOID_CARDS = 30
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY")
# Local dev/testing against the Firebase Local Emulator Suite needs no real
# service account — the emulator env vars are enough to talk to it.
USING_FIREBASE_EMULATOR = bool(os.getenv("FIRESTORE_EMULATOR_HOST") or os.getenv("FIREBASE_AUTH_EMULATOR_HOST"))
# Shared daily cap across document analysis, tutor chat and podcast audio —
# the three actions that call a paid API. One counter keeps this simple;
# split it into separate counters later if different limits are needed.
DAILY_USAGE_LIMIT = int(os.getenv("DAILY_USAGE_LIMIT", "100"))
# Comma-separated allowlist of emails permitted to use the app. Empty means
# unrestricted — set this to lock the app down to specific accounts.
ALLOWED_EMAILS = {e.strip().lower() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()}
# Free "Play episode — your device's voice" (Web Speech API) button is
# hidden by default while it's not a priority for the current prototype;
# flip ENABLE_BROWSER_VOICE=true (no code change, just an env var + redeploy)
# to bring it back. The frontend reads this from /api/health.
ENABLE_BROWSER_VOICE = os.getenv("ENABLE_BROWSER_VOICE", "false").strip().lower() == "true"
# Where "Give feedback" submissions get emailed. Feedback is always saved to
# Firestore regardless; email is best-effort and skipped if RESEND_API_KEY
# isn't set.
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FEEDBACK_EMAIL_TO = os.getenv("FEEDBACK_EMAIL_TO")
FEEDBACK_EMAIL_FROM = os.getenv("FEEDBACK_EMAIL_FROM", "Syrora Feedback <onboarding@resend.dev>")


def get_gemini_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def get_google_tts_api_key() -> str | None:
    # Cloud TTS accepts plain API keys; a dedicated key can be set, but the
    # Gemini key works too once the Cloud TTS API is enabled on its project.
    return os.getenv("GOOGLE_TTS_API_KEY") or get_gemini_api_key()


def get_elevenlabs_api_key() -> str | None:
    return os.getenv("ELEVENLABS_API_KEY")
