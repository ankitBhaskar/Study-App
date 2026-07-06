# API Integrations

Reference for every external API this app calls: where the integration lives in code,
exactly what prompt/request is sent, and the input/output shape. All backend code is in
`api/index.py`; all frontend call sites are in `src/App.jsx` unless noted.

For deployment/env-var setup, see [README.md](README.md). This file is about *what* is
sent to each API and *where* in the code, not how to configure keys.

---

## 1. Google Gemini (`generativelanguage.googleapis.com`)

Gemini is used for four things: study-content generation, Tutor chat, per-section
regeneration (quiz/summary/podcast), and — by default — podcast **text-to-speech** (§2).

- Base URL: `GEMINI_API_BASE` env var, default `https://generativelanguage.googleapis.com/v1beta`
- Model (text): `GEMINI_MODEL` env var, default `gemini-2.5-flash` (`api/index.py:38`)
- Auth: `x-goog-api-key` header, key from `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
- Shared text transport: `call_gemini()` — `api/index.py:737-785`

### 1.1 Shared transport — `call_gemini()`

**File/line:** `api/index.py:737`

**Request built** (`api/index.py:748-761`):

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

Response parsed at `api/index.py:776-785`. Raises `HTTPException(502)` on non-200,
unexpected shape, or empty completion.

### 1.2 Shared style/length guidance

`PODCAST_STYLE_GUIDANCE` (`api/index.py:808`) and `SUMMARY_LENGTH_GUIDANCE`
(`api/index.py:826`) back both the combined analysis prompt and the standalone regenerate
prompts, so a chosen style/length reads consistently either way.

- **Podcast styles** `{"conversation", "solo", "interview"}` — two-host banter / single narrator / host+expert-guest. Invalid → `conversation`.
- **Summary lengths** `{"concise", "detailed"}` — 4–6 vs 8–12 key points. Invalid → `concise`.
- Optional `focus` (≤200 chars) appends `Focus specifically on this topic … skip parts of the document unrelated to it.`
- **Podcast script length cap:** both podcast prompts explicitly instruct Gemini to keep
  the *combined spoken text of all segments* under `MAX_PODCAST_SCRIPT_CHARS` = 4,500
  characters (`api/index.py:81`) — see §1.3/§1.7 for the prompt wording and §1.8 for the
  server-side enforcement, since an LLM asked for a character budget won't always hit it
  exactly.

### 1.3 Study analysis (`POST /api/pdf/analyze`)

**Handler:** `api/index.py:1170` · **Frontend:** `src/App.jsx:329`

Multipart form: `file: UploadFile` (PDF ≤4 MB, `read_pdf_upload()` at `api/index.py:1011`)
plus optional `podcast_style` / `summary_length` / `summary_focus` Form fields and the
`Authorization` header.

**Prompt** built by `build_study_system_instruction()` (`api/index.py:846-876`) — a single
JSON-shaped instruction producing `title` + `summary` + `quiz` + `podcastScript`, with the
summary/podcast guidance lines swapped in from §1.2, including the line:

```
Keep the combined spoken text of all podcast segments under 4500 characters total — write shorter, punchier lines rather than fewer segments.
```

**User content:**

```
File name: {file_name}

Extracted PDF content:

{context}   # extracted text, truncated to MAX_GEMINI_CONTEXT_CHARS = 400,000 chars (api/index.py:36)
```

Called at `api/index.py:1205`. Normalised by `normalise_study_content()`
(`api/index.py:993`) via `parse_summary_points()` (`api/index.py:947`),
`parse_quiz_questions()` (`api/index.py:921`), `parse_podcast_script()` (`api/index.py:953`,
see §1.8 for the character-cap enforcement).

**Output — `StudyAnalysisResponse`, `api/index.py:171-184`:**

```json
{
  "file_name": "string", "page_count": 0, "title": "string",
  "summary": ["string"],
  "quiz": [ { "q": "string", "options": ["string"], "answer": 0, "topic": "string", "explanation": "string" } ],
  "podcast": { "duration": "10:00", "hosts": ["name"], "transcript": [ { "t": "0:00", "who": "name", "line": "string" } ] },
  "document_context": "string (echoed extracted text)",
  "document_id": "string | null"
}
```

### 1.4 Tutor chat (`POST /api/chat`)

**Handler:** `api/index.py:1241` · **Frontend:** `src/App.jsx:1318` (`TutorPanel.send()`)

Per-request system prompt: *"You are a friendly study tutor. Answer questions using ONLY
the uploaded document below…"* + file name + document context. Last 20 turns passed as
`contents`; called plain-text (`json_response=False`).

**Input — `ChatRequest`, `api/index.py:192-196`** · **Output — `ChatResponse`, `api/index.py:199-200`** (`{ "answer": "string" }`).

### 1.5 Quiz regeneration (`POST /api/documents/{doc_id}/quiz/regenerate`)

**Handler:** `api/index.py:1322` · **Frontend:** `src/App.jsx:801`

Prompt `QUIZ_SYSTEM_INSTRUCTION` (`api/index.py:904`). Avoid-list = current quiz + last 5
attempts' questions, capped at `MAX_AVOID_QUESTIONS` = 30 (`api/index.py:92`). Overwrites
stored `quiz`. Output `QuizRegenerateResponse` (`api/index.py:234-235`).

### 1.6 Summary regeneration (`POST /api/documents/{doc_id}/summary/regenerate`)

**Handler:** `api/index.py:1384` · **Frontend:** `src/App.jsx:656`

Prompt `build_summary_system_instruction()` (`api/index.py:879-885`). Overwrites stored
`summary`. Input `SummaryRegenerateRequest` (`api/index.py:238-240`, `{length, focus}`),
output `SummaryRegenerateResponse` (`api/index.py:243-244`).

### 1.7 Podcast script regeneration (`POST /api/documents/{doc_id}/podcast/regenerate`)

**Handler:** `api/index.py:1419` · **Frontend:** `src/App.jsx:973`

Prompt `build_podcast_system_instruction()` (`api/index.py:889-901`) — same style guidance
and the same `MAX_PODCAST_SCRIPT_CHARS` character-budget line as §1.3. On success it
**deletes the document's cached segment audio** — the new script no longer matches old
audio at the same indices — then overwrites stored `podcast`. Input
`PodcastRegenerateRequest` (`api/index.py:247-248`, `{style}`), output
`PodcastRegenerateResponse` (`api/index.py:251-252`).

### 1.8 Podcast script length enforcement — `parse_podcast_script()`

**File/line:** `api/index.py:953-990` (shared by §1.3 and §1.7 — both the initial analysis
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

---

## 2. Podcast text-to-speech — free browser voice (default player) or paid AI narration

**The default podcast player calls no external API at all.** It uses the browser's
built-in Web Speech API (`window.speechSynthesis`) entirely client-side —
`pickBrowserVoices()` (`src/App.jsx:937`) and the playback functions in `PodcastPanel`
(`src/App.jsx:1006-1049`). Free, instant, no quota, works offline. This is what's shown
first in the UI ("Play episode").

A separate, explicitly opt-in **"Generate AI-narrated audio"** button (never triggered
automatically — it's a paid/quota-limited call) uses the backend endpoint below.

**Backend AI narration — Gemini TTS (default) or ElevenLabs**

Each podcast transcript line is synthesised to audio. The backend is selected by
**`TTS_PROVIDER`** (`api/index.py:55`), default **`gemini`** (much cheaper); set
`TTS_PROVIDER=elevenlabs` to use ElevenLabs instead. Both paths live in the code; only the
selected one runs. Dispatch is in the segment-audio handler (`api/index.py:1732`).

**Endpoint:** `POST /api/podcast/segment-audio` — handler at `api/index.py:1711`
**Frontend call site:** `src/App.jsx` (`PodcastPanel`'s `ensureSegmentUrl()`, only called
once the user taps "Generate AI-narrated audio"). `generateAudioFor` fetches segments
**strictly sequentially** — a cache miss generates a whole batch server-side, so two
concurrent misses would each fire an expensive batch call and trip the free tier's
3-requests/minute limit. Fetches go through `fetchSegmentWithRecovery()`: a batch request
can sit minutes with nothing on the wire and mobile networks/proxies kill idle connections,
but the serverless function keeps running and caches the batch anyway — so on a network
drop or gateway 5xx the frontend polls `GET /api/podcast/audio-status/{doc_id}` (free)
until the segment appears cached, then re-requests it as an instant cache hit; it only
re-generates if the segment never appears (3 attempts total, non-5xx HTTP errors thrown
immediately). The frontend is provider-agnostic: it reads `res.blob()` and plays it, so WAV
or MP3 both work.

A cache check runs first (`api/index.py:1716`): if `document_id` + `segment_index` are given
and that segment was already generated, the stored bytes are returned with their stored MIME
(no TTS call). See §4.

**Gemini path generates audio in BATCHES of segments, not one call per segment.** When a
Gemini-provider request carries a `document_id` + `segment_index` (i.e. it's tied to a saved
document, not an ad-hoc preview), the handler (`api/index.py:1739-1768`) fetches that
document's full transcript from Firestore and calls `gemini_tts_batch()`
(`api/index.py:1625-1709`) once for the batch of consecutive segments containing the
requested one, then caches every resulting segment via `save_segment_audio()` and calls
`increment_usage()` once per batch. Two earlier designs both failed in production:
one-call-per-segment (up to ~12 calls per episode) burned through the free tier's
3-requests/minute limit (429s), and one-call-per-episode timed out — a full 4,500-char
script is ~5 minutes of audio, which Gemini can't synthesize inside a serverless request
window (504s). Batches are the middle ground: `GEMINI_TTS_BATCH_CHARS` = 2,250 spoken
characters per call (`api/index.py:70`, env-overridable), so a max-length script needs
exactly 2 calls and each finishes well inside `maxDuration: 300` (`vercel.json`). TTS calls
get their own `GEMINI_TTS_TIMEOUT_SECONDS` = 280s (`api/index.py:64`) instead of the 55s
text-completion timeout. If there's no matching document/transcript (e.g. an ad-hoc
single-line preview), it falls back to the single-segment `gemini_tts()` call
(`api/index.py:1770-1775`). The ElevenLabs path (§2.2) is unchanged — it stays one call per
segment, since ElevenLabs's TTS endpoint used here has no multi-speaker/batch mode.

- `_tts_batch_bounds()` (`api/index.py:1603-1622`) groups consecutive segments greedily
  into batches of ≤ `GEMINI_TTS_BATCH_CHARS` spoken characters (a single line longer than
  the cap gets a batch of its own) and returns the bounds of the batch containing the
  requested segment.
- `gemini_tts_batch()` builds one "SpeakerName: line" block of text for the batch
  (mirroring the frontend's own `seg.who === hosts[0] ? 0 : 1` speaker mapping), then calls
  Gemini once:
  - **Two hosts speak:** uses
    `generationConfig.speechConfig.multiSpeakerVoiceConfig.speakerVoiceConfigs[]` (each host
    name mapped to `GEMINI_TTS_VOICE_A`/`_B`) — both voices synthesised in one response.
    Speaker name labels are a synthesis directive only; they are not spoken aloud.
  - **Only one host speaks** (solo narration): falls back to the plain single-voice
    `speechConfig.voiceConfig` shape (same as `gemini_tts()`, §2.1).
  - The batch's PCM response is sliced into one WAV clip per segment by
    `_split_pcm_by_chars()` (`api/index.py:1579-1600`) — sample boundaries are placed
    proportional to each segment's share of the batch's character count (a heuristic, since
    Gemini returns no per-segment timing), aligned to whole 16-bit samples.
  - Sliced segments from a long script can exceed one Firestore document, so cached audio
    is **chunked**: `save_segment_audio()` (`api/index.py:482`) splits anything over
    `MAX_CACHED_AUDIO_BYTES` = 740,000 raw bytes (`api/index.py:74`) across sibling chunk
    documents (`{index}.c{n}`, `_audio_chunk_ref()` at `api/index.py:442`) and
    `get_cached_segment_audio()` (`api/index.py:456`) reassembles them; a missing chunk is
    treated as a cache miss. Chunk documents have non-integer IDs, so
    `list_cached_segment_indices()` skips them and the collection-wide delete loops (§4)
    still clean them up. Pre-chunking cache documents (no `chunks` field) read as before.

### 2.1 Gemini TTS (default) — `gemini_tts()`, `api/index.py:1529-1576`

- Model: `GEMINI_TTS_MODEL` env var, default `gemini-2.5-flash-preview-tts` (`api/index.py:56`)
- Voices: `GEMINI_TTS_VOICE_A` / `GEMINI_TTS_VOICE_B`, default `Kore` / `Puck` (`api/index.py:59-60`), chosen by `request.speaker` (0/1)
- Auth: `x-goog-api-key` header, reuses `GEMINI_API_KEY`

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
browsers can't play directly, so `pcm_to_wav()` (`api/index.py:1469-1483`) wraps it in a WAV
header (sample rate parsed from the mimeType). **Output:** `audio/wav` bytes.

### 2.2 ElevenLabs (opt-in) — `elevenlabs_tts()`, `api/index.py:1486-1526`

- Base URL: `ELEVENLABS_API_BASE`, default `https://api.elevenlabs.io/v1`; model `ELEVENLABS_MODEL`, default `eleven_multilingual_v2`
- Auth: `xi-api-key` header, key from `ELEVENLABS_API_KEY`
- Voices resolved from the account via `resolve_voice_ids()` (`api/index.py:311-340`; avoids the free-tier 402 on library voices), cached in-process (`_cached_voice_ids`, `api/index.py:308`); `ELEVENLABS_VOICE_HOST_A/B` override when both set

```
POST {ELEVENLABS_API_BASE}/text-to-speech/{voice_id}?output_format=mp3_44100_128
Header: xi-api-key: <ELEVENLABS_API_KEY>

{ "text": "<line, ≤1000 chars — MAX_SEGMENT_TEXT_CHARS, api/index.py:75>",
  "model_id": "eleven_multilingual_v2",
  "voice_settings": { "stability": 0.5, "similarity_boost": 0.75 } }
```

**Output:** `audio/mpeg` bytes.

**Input to the endpoint — `SegmentAudioRequest`, `api/index.py:255-262`:**

```json
{ "text": "string", "speaker": 0, "document_id": "string | null", "segment_index": 0 }
```

---

## 3. Firebase Authentication

Gates uploading, chat, regeneration and podcast audio behind sign-in; identifies the user
for storage and usage limits.

- **Backend:** `require_user()` (`api/index.py:395-417`) — FastAPI dependency (`Depends(require_user)`). Reads `Authorization: Bearer <idToken>`, verifies via `firebase_auth.verify_id_token()`, enforces the `ALLOWED_EMAILS` allowlist (403), returns `AuthedUser {uid, email}` (`api/index.py:269-271`). Admin init: `get_firebase_app()` (`api/index.py:349-370`).
- **Frontend:** `src/firebase.js` inits the client SDK. Sign-in `signInWithEmailAndPassword` (`src/App.jsx:138`); session watch `onAuthStateChanged` (`src/App.jsx:204`); `authedFetch()` (`src/App.jsx:206`) attaches `auth.currentUser.getIdToken()` (`src/App.jsx:207`) as a Bearer token on every call.

---

## 4. Firebase Firestore (Admin SDK)

Storage only — no LLM/TTS cost (the regenerate endpoints do call Gemini, but that cost is
the Gemini call, not the Firestore write). Client: `get_firestore_client()`
(`api/index.py:376-392`). Layout under `users/{uid}/documents/{doc_id}`:

| Path | Written by | File/line | Contents |
|---|---|---|---|
| `documents/{doc_id}` | `analyze_pdf()` | `api/index.py:1170` | `title`, `file_name`, `summary`, `quiz`, `podcast`, `document_context` (≤`MAX_STORED_CONTEXT_BYTES` = 900 KB, `api/index.py:88`), `created_at`. `summary`/`quiz`/`podcast` are overwritten in place by §1.5–1.7 |
| `documents/{doc_id}/audio/{segment_index}` | `save_segment_audio()` | `api/index.py:482` | `{ "data": "<base64 audio>", "mime": "audio/wav" \| "audio/mpeg", "chunks": N }` — one doc per segment. Audio over `MAX_CACHED_AUDIO_BYTES` = 740 KB raw (`api/index.py:74`, e.g. a long Gemini WAV slice) is split across sibling chunk docs `{segment_index}.c{n}` (`{ "data": ... }` only) and reassembled on read by `get_cached_segment_audio()` (`api/index.py:456`); a missing chunk reads as a cache miss. Chunk doc IDs aren't integers, so `list_cached_segment_indices()` ignores them. The whole subcollection (chunks included) is dropped on podcast regeneration (§1.7) |
| `documents/{doc_id}/chat/log` | `save_chat_log()` | `api/index.py:1289` | `{ "messages": [...] }` — last `MAX_STORED_CHAT_MESSAGES` = 60, each text ≤`MAX_STORED_CHAT_TEXT_BYTES` = 10 KB (`api/index.py:84-85`) |
| `documents/{doc_id}/quiz_attempts/{auto_id}` | `save_quiz_attempt()` | `api/index.py:529-562` | `{ questions, answers, score, total, created_at }` — score computed server-side; capped at `MAX_QUIZ_ATTEMPTS` = 20 (`api/index.py:91`) |
| `usage/{yyyy-mm-dd}` | `increment_usage()` | `api/index.py:627-632` | `{ count, date }` — shared daily counter across analyze/chat/quiz-/summary-/podcast-regenerate/audio-generate |

Reads: `list_documents()` (`api/index.py:1072`), `get_document()` (`api/index.py:1102`),
`get_cached_segment_audio()` (`api/index.py:456`, returns bytes + MIME; legacy docs without
`mime` default to `audio/mpeg`), `list_cached_segment_indices()` (`api/index.py:590-610`),
`get_chat_log()` (`api/index.py:1275`), `list_quiz_attempts()` (`api/index.py:565-589`).
Deletes cascade to `audio`/`chat`/`quiz_attempts` via `_delete_document_and_subcollections()`
(`api/index.py:1121-1131`). Two small shared helpers back the regenerate endpoints:
`_get_document_or_404()` (`api/index.py:1365-1371`) and `_require_document_context()`
(`api/index.py:1374-1381`).

---

## Internal REST API

| Method | Path | Auth | Handler | External API |
|---|---|---|---|---|
| GET | `/api/health` | none | `api/index.py:1032` | — (reports `tts_provider`) |
| GET | `/api/profile` | required | `api/index.py:1049` | Firestore |
| GET | `/api/documents` | required | `api/index.py:1072` | Firestore |
| GET | `/api/documents/{doc_id}` | required | `api/index.py:1102` | Firestore |
| DELETE | `/api/documents/{doc_id}` | required | `api/index.py:1134` | Firestore |
| DELETE | `/api/documents` | required | `api/index.py:1143` | Firestore |
| POST | `/api/pdf/prepare` | none | `api/index.py:1152` | — |
| POST | `/api/pdf/analyze` | required | `api/index.py:1170` | Gemini, Firestore |
| POST | `/api/chat` | required | `api/index.py:1241` | Gemini |
| GET | `/api/documents/{doc_id}/chat` | required | `api/index.py:1275` | Firestore |
| PUT | `/api/documents/{doc_id}/chat` | required | `api/index.py:1289` | Firestore |
| GET | `/api/documents/{doc_id}/quiz/attempts` | required | `api/index.py:1306` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/attempts` | required | `api/index.py:1311` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/regenerate` | required | `api/index.py:1322` | Gemini, Firestore |
| POST | `/api/documents/{doc_id}/summary/regenerate` | required | `api/index.py:1384` | Gemini, Firestore |
| POST | `/api/documents/{doc_id}/podcast/regenerate` | required | `api/index.py:1419` | Gemini, Firestore |
| GET | `/api/podcast/audio-status/{doc_id}` | required | `api/index.py:1459` | Firestore |
| POST | `/api/podcast/segment-audio` | required | `api/index.py:1711` | Gemini TTS (1 call per ≤2,250-char batch of segments) **or** ElevenLabs (1 call/segment, on cache miss), Firestore |

"Required" auth means `Depends(require_user)` — see §3.
