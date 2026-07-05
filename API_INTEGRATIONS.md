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
- Shared text transport: `call_gemini()` — `api/index.py:689-737`

### 1.1 Shared transport — `call_gemini()`

**File/line:** `api/index.py:689`

**Request built** (`api/index.py:700-713`):

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

Response parsed at `api/index.py:728-737`. Raises `HTTPException(502)` on non-200,
unexpected shape, or empty completion.

### 1.2 Shared style/length guidance

`PODCAST_STYLE_GUIDANCE` (`api/index.py:760`) and `SUMMARY_LENGTH_GUIDANCE`
(`api/index.py:778`) back both the combined analysis prompt and the standalone regenerate
prompts, so a chosen style/length reads consistently either way.

- **Podcast styles** `{"conversation", "solo", "interview"}` (`api/index.py:57`) — two-host banter / single narrator / host+expert-guest. Invalid → `conversation`.
- **Summary lengths** `{"concise", "detailed"}` (`api/index.py:58`) — 4–6 vs 8–12 key points. Invalid → `concise`.
- Optional `focus` (≤200 chars) appends `Focus specifically on this topic … skip parts of the document unrelated to it.`

### 1.3 Study analysis (`POST /api/pdf/analyze`)

**Handler:** `api/index.py:1106` · **Frontend:** `src/App.jsx:329`

Multipart form: `file: UploadFile` (PDF ≤4 MB, `read_pdf_upload()` at `api/index.py:947`)
plus optional `podcast_style` / `summary_length` / `summary_focus` Form fields
(`api/index.py:1111-1113`) and the `Authorization` header.

**Prompt** built by `build_study_system_instruction()` (`api/index.py:798-827`) — a single
JSON-shaped instruction producing `title` + `summary` + `quiz` + `podcastScript`, with the
summary and podcast lines swapped in from §1.2. **User content** (`api/index.py:1131`):

```
File name: {file_name}

Extracted PDF content:

{context}   # extracted text, truncated to MAX_GEMINI_CONTEXT_CHARS = 400,000 chars (api/index.py:36)
```

Called at `api/index.py:1140`. Normalised by `normalise_study_content()`
(`api/index.py:929`) via `parse_summary_points()` (`api/index.py:897`),
`parse_quiz_questions()` (`api/index.py:871`), `parse_podcast_script()` (`api/index.py:903`).

**Output — `StudyAnalysisResponse`, `api/index.py:156-169`:**

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

**Handler:** `api/index.py:1177` · **Frontend:** `src/App.jsx:1318` (`TutorPanel.send()`)

Per-request system prompt (`api/index.py:1190`): *"You are a friendly study tutor. Answer
questions using ONLY the uploaded document below…"* + file name + document context. Last
20 turns passed as `contents`; called plain-text (`json_response=False`) at `api/index.py:1206`.

**Input — `ChatRequest`, `api/index.py:177-181`** · **Output — `ChatResponse`, `api/index.py:184-185`** (`{ "answer": "string" }`).

### 1.5 Quiz regeneration (`POST /api/documents/{doc_id}/quiz/regenerate`)

**Handler:** `api/index.py:1258` · **Frontend:** `src/App.jsx:801`

Prompt `QUIZ_SYSTEM_INSTRUCTION` (`api/index.py:854`). Avoid-list = current quiz + last 5
attempts' questions, capped at `MAX_AVOID_QUESTIONS` = 30 (`api/index.py:1267-1269`).
Called at `api/index.py:1291`; overwrites stored `quiz` (`api/index.py:1296`).
Output `QuizRegenerateResponse` (`api/index.py:219-220`).

### 1.6 Summary regeneration (`POST /api/documents/{doc_id}/summary/regenerate`)

**Handler:** `api/index.py:1320` · **Frontend:** `src/App.jsx:656`

Prompt `build_summary_system_instruction()` (`api/index.py:830`). Called at
`api/index.py:1345`; overwrites stored `summary` (`api/index.py:1350`).
Input `SummaryRegenerateRequest` (`api/index.py:223-225`, `{length, focus}`),
output `SummaryRegenerateResponse` (`api/index.py:228-229`).

### 1.7 Podcast script regeneration (`POST /api/documents/{doc_id}/podcast/regenerate`)

**Handler:** `api/index.py:1355` · **Frontend:** `src/App.jsx:973`

Prompt `build_podcast_system_instruction()` (`api/index.py:840`). Called at
`api/index.py:1379`. On success it **deletes the document's cached segment audio**
(`api/index.py:1387`) — the new script no longer matches old audio at the same indices —
then overwrites stored `podcast` (`api/index.py:1390`). Input `PodcastRegenerateRequest`
(`api/index.py:232-233`, `{style}`), output `PodcastRegenerateResponse` (`api/index.py:236-237`).

---

## 2. Podcast text-to-speech — Gemini TTS (default) or ElevenLabs

Each podcast transcript line is synthesised to audio. The backend is selected by
**`TTS_PROVIDER`** (`api/index.py:55`), default **`gemini`** (much cheaper); set
`TTS_PROVIDER=elevenlabs` to use ElevenLabs instead. Both paths live in the code; only the
selected one runs. Dispatch is in the segment-audio handler (`api/index.py:1536`).

**Endpoint:** `POST /api/podcast/segment-audio` — handler at `api/index.py:1515`
**Frontend call site:** `src/App.jsx:1062` (`PodcastPanel`'s `ensureSegmentUrl()`). The
frontend is provider-agnostic: it reads `res.blob()` and plays it, so WAV or MP3 both work.

A cache check runs first (`api/index.py:1521`): if `document_id` + `segment_index` are given
and that segment was already generated, the stored bytes are returned with their stored MIME
(no TTS call). See §4.

### 2.1 Gemini TTS (default) — `gemini_tts()`, `api/index.py:1465-1512`

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
browsers can't play directly, so `pcm_to_wav()` (`api/index.py:1405`) wraps it in a WAV
header (sample rate parsed from the mimeType). **Output:** `audio/wav` bytes.

### 2.2 ElevenLabs (opt-in) — `elevenlabs_tts()`, `api/index.py:1422-1462`

- Base URL: `ELEVENLABS_API_BASE`, default `https://api.elevenlabs.io/v1`; model `ELEVENLABS_MODEL`, default `eleven_multilingual_v2`
- Auth: `xi-api-key` header, key from `ELEVENLABS_API_KEY`
- Voices resolved from the account via `resolve_voice_ids()` (`api/index.py:296`; avoids the free-tier 402 on library voices), cached in-process (`_cached_voice_ids`, `api/index.py:293`); `ELEVENLABS_VOICE_HOST_A/B` override when both set

```
POST {ELEVENLABS_API_BASE}/text-to-speech/{voice_id}?output_format=mp3_44100_128
Header: xi-api-key: <ELEVENLABS_API_KEY>

{ "text": "<line, ≤1000 chars — MAX_SEGMENT_TEXT_CHARS, api/index.py:66>",
  "model_id": "eleven_multilingual_v2",
  "voice_settings": { "stability": 0.5, "similarity_boost": 0.75 } }
```

**Output:** `audio/mpeg` bytes.

**Input to the endpoint — `SegmentAudioRequest`, `api/index.py:240-247`:**

```json
{ "text": "string", "speaker": 0, "document_id": "string | null", "segment_index": 0 }
```

---

## 3. Firebase Authentication

Gates uploading, chat, regeneration and podcast audio behind sign-in; identifies the user
for storage and usage limits.

- **Backend:** `require_user()` (`api/index.py:380`) — FastAPI dependency (`Depends(require_user)`). Reads `Authorization: Bearer <idToken>`, verifies via `firebase_auth.verify_id_token()`, enforces the `ALLOWED_EMAILS` allowlist (403), returns `AuthedUser {uid, email}` (`api/index.py:254-256`). Admin init: `get_firebase_app()` (`api/index.py:334`).
- **Frontend:** `src/firebase.js` inits the client SDK. Sign-in `signInWithEmailAndPassword` (`src/App.jsx:138`); session watch `onAuthStateChanged` (`src/App.jsx:204`); `authedFetch()` (`src/App.jsx:206`) attaches `auth.currentUser.getIdToken()` (`src/App.jsx:207`) as a Bearer token on every call.

---

## 4. Firebase Firestore (Admin SDK)

Storage only — no LLM/TTS cost (the regenerate endpoints do call Gemini, but that cost is
the Gemini call, not the Firestore write). Client: `get_firestore_client()`
(`api/index.py:361`). Layout under `users/{uid}/documents/{doc_id}`:

| Path | Written by | File/line | Contents |
|---|---|---|---|
| `documents/{doc_id}` | `analyze_pdf()` | `api/index.py:1152-1162` | `title`, `file_name`, `summary`, `quiz`, `podcast`, `document_context` (≤`MAX_STORED_CONTEXT_BYTES` = 900 KB, `api/index.py:73`), `created_at`. `summary`/`quiz`/`podcast` are overwritten in place by §1.5–1.7 |
| `documents/{doc_id}/audio/{segment_index}` | `save_segment_audio()` | `api/index.py:443` | `{ "data": "<base64 audio>", "mime": "audio/wav" \| "audio/mpeg" }` — one doc per segment. Segments over `MAX_CACHED_AUDIO_BYTES` = 740 KB (`api/index.py:65`, e.g. long Gemini WAV) are served but **not** cached, keeping each doc under Firestore's 1 MiB cap. The whole subcollection is dropped on podcast regeneration (§1.7) |
| `documents/{doc_id}/chat/log` | `save_chat_log()` | `api/index.py:1225` | `{ "messages": [...] }` — last `MAX_STORED_CHAT_MESSAGES` = 60, each text ≤`MAX_STORED_CHAT_TEXT_BYTES` = 10 KB (`api/index.py:69-70`) |
| `documents/{doc_id}/quiz_attempts/{auto_id}` | `save_quiz_attempt()` | `api/index.py:481` | `{ questions, answers, score, total, created_at }` — score computed server-side; capped at `MAX_QUIZ_ATTEMPTS` = 20 (`api/index.py:76`) |
| `usage/{yyyy-mm-dd}` | `increment_usage()` | `api/index.py:579` | `{ count, date }` — shared daily counter across analyze/chat/quiz-/summary-/podcast-regenerate/audio-generate |

Reads: `list_documents()` (`api/index.py:1008`), `get_document()` (`api/index.py:1038`),
`get_cached_segment_audio()` (`api/index.py:427`, returns bytes + MIME; legacy docs without
`mime` default to `audio/mpeg`), `list_cached_segment_indices()` (`api/index.py:542`),
`get_chat_log()` (`api/index.py:1211`), `list_quiz_attempts()` (`api/index.py:517`).
Deletes cascade to `audio`/`chat`/`quiz_attempts` via `_delete_document_and_subcollections()`
(`api/index.py:1057`).

---

## Internal REST API

| Method | Path | Auth | Handler | External API |
|---|---|---|---|---|
| GET | `/api/health` | none | `api/index.py:968` | — (reports `tts_provider`) |
| GET | `/api/profile` | required | `api/index.py:985` | Firestore |
| GET | `/api/documents` | required | `api/index.py:1008` | Firestore |
| GET | `/api/documents/{doc_id}` | required | `api/index.py:1038` | Firestore |
| DELETE | `/api/documents/{doc_id}` | required | `api/index.py:1070` | Firestore |
| DELETE | `/api/documents` | required | `api/index.py:1079` | Firestore |
| POST | `/api/pdf/prepare` | none | `api/index.py:1088` | — |
| POST | `/api/pdf/analyze` | required | `api/index.py:1106` | Gemini, Firestore |
| POST | `/api/chat` | required | `api/index.py:1177` | Gemini |
| GET | `/api/documents/{doc_id}/chat` | required | `api/index.py:1211` | Firestore |
| PUT | `/api/documents/{doc_id}/chat` | required | `api/index.py:1225` | Firestore |
| GET | `/api/documents/{doc_id}/quiz/attempts` | required | `api/index.py:1242` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/attempts` | required | `api/index.py:1247` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/regenerate` | required | `api/index.py:1258` | Gemini, Firestore |
| POST | `/api/documents/{doc_id}/summary/regenerate` | required | `api/index.py:1320` | Gemini, Firestore |
| POST | `/api/documents/{doc_id}/podcast/regenerate` | required | `api/index.py:1355` | Gemini, Firestore |
| GET | `/api/podcast/audio-status/{doc_id}` | required | `api/index.py:1395` | Firestore |
| POST | `/api/podcast/segment-audio` | required | `api/index.py:1515` | Gemini TTS **or** ElevenLabs (on cache miss), Firestore |

"Required" auth means `Depends(require_user)` — see §3.
