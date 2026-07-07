# API Integrations

Reference for every external API this app calls: where the integration lives in code,
exactly what prompt/request is sent, and the input/output shape. All backend code is in
`api/index.py`; all frontend call sites are in `src/App.jsx` unless noted.

For deployment/env-var setup, see [README.md](README.md). This file is about *what* is
sent to each API and *where* in the code, not how to configure keys.

---

## 1. Google Gemini (`generativelanguage.googleapis.com`)

Gemini is used for study-content generation, Tutor chat, per-section regeneration
(quiz/summary/podcast), and — opt-in via `TTS_PROVIDER=gemini` — podcast
**text-to-speech** (§2.2; the default TTS is Google Cloud Text-to-Speech, §2.1).

- Base URL: `GEMINI_API_BASE` env var, default `https://generativelanguage.googleapis.com/v1beta`
- Model (text): `GEMINI_MODEL` env var, default `gemini-2.5-flash` (`api/index.py:38`)
- Auth: `x-goog-api-key` header, key from `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
- Shared text transport: `call_gemini()` — `api/index.py:784-832`

### 1.1 Shared transport — `call_gemini()`

**File/line:** `api/index.py:784`

**Request built** (`api/index.py:795-808`):

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

Response parsed at `api/index.py:823-832`. Raises `HTTPException(502)` on non-200,
unexpected shape, or empty completion.

### 1.2 Shared style/length guidance

`PODCAST_STYLE_GUIDANCE` (`api/index.py:855`) and `SUMMARY_LENGTH_GUIDANCE`
(`api/index.py:873`) back both the combined analysis prompt and the standalone regenerate
prompts, so a chosen style/length reads consistently either way.

- **Podcast styles** `{"conversation", "solo", "interview"}` — two-host banter / single narrator / host+expert-guest. Invalid → `conversation`.
- **Summary lengths** `{"concise", "detailed"}` — 4–6 vs 8–12 key points. Invalid → `concise`.
- Optional `focus` (≤200 chars) appends `Focus specifically on this topic … skip parts of the document unrelated to it.`
- **Podcast script length cap:** both podcast prompts explicitly instruct Gemini to keep
  the *combined spoken text of all segments* under `MAX_PODCAST_SCRIPT_CHARS` = 4,500
  characters (`api/index.py:95`) — see §1.3/§1.7 for the prompt wording and §1.8 for the
  server-side enforcement, since an LLM asked for a character budget won't always hit it
  exactly.

### 1.3 Study analysis (`POST /api/pdf/analyze`)

**Handler:** `api/index.py:1219` · **Frontend:** `src/App.jsx:329`

Multipart form: `file: UploadFile` (PDF ≤4 MB, `read_pdf_upload()` at `api/index.py:1058`)
plus optional `podcast_style` / `summary_length` / `summary_focus` Form fields and the
`Authorization` header.

**Prompt** built by `build_study_system_instruction()` (`api/index.py:893-923`) — a single
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

Called at `api/index.py:1254`. Normalised by `normalise_study_content()`
(`api/index.py:1040`) via `parse_summary_points()` (`api/index.py:994`),
`parse_quiz_questions()` (`api/index.py:968`), `parse_podcast_script()` (`api/index.py:1000`,
see §1.8 for the character-cap enforcement).

**Output — `StudyAnalysisResponse`, `api/index.py:185-198`:**

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

**Handler:** `api/index.py:1297` · **Frontend:** `src/App.jsx:1318` (`TutorPanel.send()`)

Per-request system prompt: *"You are a friendly study tutor. Answer questions using ONLY
the uploaded document below…"* + file name + document context. Last 20 turns passed as
`contents`; called plain-text (`json_response=False`).

**Input — `ChatRequest`, `api/index.py:211-215`** · **Output — `ChatResponse`, `api/index.py:218-219`** (`{ "answer": "string" }`).

### 1.5 Quiz regeneration (`POST /api/documents/{doc_id}/quiz/regenerate`)

**Handler:** `api/index.py:1378` · **Frontend:** `src/App.jsx:801`

Prompt `QUIZ_SYSTEM_INSTRUCTION` (`api/index.py:951`). Avoid-list = current quiz + last 5
attempts' questions, capped at `MAX_AVOID_QUESTIONS` = 30 (`api/index.py:106`). Overwrites
stored `quiz`. Output `QuizRegenerateResponse` (`api/index.py:253-254`).

### 1.6 Summary regeneration (`POST /api/documents/{doc_id}/summary/regenerate`)

**Handler:** `api/index.py:1440` · **Frontend:** `src/App.jsx:656`

Prompt `build_summary_system_instruction()` (`api/index.py:926-932`). Overwrites stored
`summary`. Input `SummaryRegenerateRequest` (`api/index.py:257-259`, `{length, focus}`),
output `SummaryRegenerateResponse` (`api/index.py:262-263`).

### 1.7 Podcast style switch / regeneration (`POST /api/documents/{doc_id}/podcast/regenerate`)

**Handler:** `api/index.py:1482` · **Frontend:** `src/App.jsx` (`regenerateScript`)

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
  `build_podcast_system_instruction()` (`api/index.py:936-948`) — same style guidance and
  `MAX_PODCAST_SCRIPT_CHARS` budget as §1.3 — saves the new version, makes it active, and
  clears only that style's own audio namespace (other styles keep theirs).
- **Pre-versioning documents** are migrated on first touch: the existing script is adopted
  as the saved version of its guessed style (`_guess_podcast_style()`, host count) with
  `audio_ns: "legacy"`, so audio cached under the old integer IDs stays reachable.

Input `PodcastRegenerateRequest` (`api/index.py:266-267`, `{style}`), output
`PodcastRegenerateResponse` (`api/index.py:270-276`,
`{podcast, podcast_style, saved_styles, reused}`). `saved_styles` also comes back from
`POST /api/pdf/analyze` and `GET /api/documents/{doc_id}` so the UI can mark chips on load.

### 1.8 Podcast script length enforcement — `parse_podcast_script()`

**File/line:** `api/index.py:1000-1037` (shared by §1.3 and §1.7 — both the initial analysis
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

**Backend AI narration — Google Cloud TTS (default), Gemini TTS or ElevenLabs**

Each podcast transcript line is synthesised to audio. The backend is selected by
**`TTS_PROVIDER`** (`api/index.py:56`), default **`google`** (Cloud Text-to-Speech —
synthesizes the whole episode in ONE fast call); `gemini` and `elevenlabs` remain fully
selectable. All three paths live in the code; only the selected one runs. Dispatch is in
the segment-audio handler (`api/index.py:1947`).

**Endpoint:** `POST /api/podcast/segment-audio` — handler at `api/index.py:1913`
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

A cache check runs first (`api/index.py:1923`): if `document_id` + `segment_index` are given
and that segment was already generated, the stored bytes are returned with their stored MIME
(no TTS call). See §4.

**Document-tied requests generate MANY segments per call, not one.** When a request
carries a `document_id` + `segment_index` (i.e. it's tied to a saved document, not an
ad-hoc preview), the handler (`api/index.py:1954-1979`) fetches that document's full
transcript from Firestore, generates in bulk, caches every resulting segment via
`save_segment_audio()` and calls `increment_usage()` once:

- **google (default):** `google_tts_episode()` synthesizes the ENTIRE episode in one Cloud
  TTS call (§2.1). Cloud TTS is a dedicated speech engine, not an LLM — a full 4,500-char
  script takes seconds, nowhere near the serverless deadline.
- **gemini:** `gemini_tts_batch()` generates the ~2,250-char batch around the requested
  segment (§2.2). Two earlier Gemini designs failed in production: one-call-per-segment
  burned the free tier's 3-requests/minute limit (429s) and one-call-per-episode timed out,
  since Gemini synthesizes roughly in real time (504s). `GEMINI_TTS_BATCH_CHARS` = 2,250
  (`api/index.py:84`) keeps each call inside `maxDuration: 300` (`vercel.json`), with
  `GEMINI_TTS_TIMEOUT_SECONDS` = 280s (`api/index.py:78`).

If there's no matching document/transcript (e.g. an ad-hoc single-line preview), the
handler falls back to a single-segment call (`api/index.py:1981-1990`). The ElevenLabs path
(§2.3) is unchanged — always one call per segment.

Shared plumbing for both bulk paths: the combined PCM is sliced into one WAV clip per
segment by `_split_pcm_by_chars()` (`api/index.py:1676-1697`) — boundaries proportional to
each segment's character share (a heuristic; neither API returns per-segment timing),
aligned to whole 16-bit samples. Sliced segments can exceed one Firestore document, so
cached audio is **chunked**: `save_segment_audio()` (`api/index.py:528`) splits anything
over `MAX_CACHED_AUDIO_BYTES` = 740,000 raw bytes (`api/index.py:88`) across sibling chunk
documents (`_audio_chunk_ref()`, `api/index.py:484`) and `get_cached_segment_audio()`
(`api/index.py:502`) reassembles them; a missing chunk reads as a cache miss.

### 2.1 Google Cloud Text-to-Speech (default) — `google_tts_episode()`, `api/index.py:1773-1802`

- Base URL: `GOOGLE_TTS_API_BASE`, default `https://texttospeech.googleapis.com/v1` (`api/index.py:62`)
- Auth: `x-goog-api-key` header — `GOOGLE_TTS_API_KEY`, falling back to `GEMINI_API_KEY` (`get_google_tts_api_key()`, `api/index.py:330`). **The Cloud Text-to-Speech API must be enabled on the key's Google Cloud project** (the 403 error message links to the enable page). WaveNet pricing: $4/1M chars, 1M-chars/month free tier.
- Voice: `GOOGLE_TTS_VOICE`, default `en-AU-Wavenet-D` (`api/index.py:63`); `languageCode` derived from the voice name. **One narrator voice for the whole episode** — WaveNet has no multi-speaker mode, so both hosts share it; speaker names are never included in the synthesized text.

```json
POST {GOOGLE_TTS_API_BASE}/text:synthesize
Header: x-goog-api-key: <key>

{
  "input":       { "text": "<all segment lines joined with blank lines>" },
  "voice":       { "languageCode": "en-AU", "name": "en-AU-Wavenet-D" },
  "audioConfig": { "audioEncoding": "LINEAR16", "sampleRateHertz": 24000 }
}
```

Response `{ "audioContent": "<base64 WAV>" }` — parsed by `_parse_wav()`
(`api/index.py:1700`), sliced per segment, re-wrapped by `pcm_to_wav()`. **Output:**
`audio/wav`. Cloud TTS caps input at 5,000 bytes; the 4,500-char script cap fits one call,
and `google_tts_episode()` packs segments under a defensive `GOOGLE_TTS_MAX_INPUT_BYTES` =
4,800 budget (`api/index.py:69`) — multi-byte punctuation can force a rare second call.
The transport is `_google_tts_synthesize()` (`api/index.py:1715`); `google_tts()`
(`api/index.py:1767`) handles ad-hoc single segments. Timeout
`GOOGLE_TTS_TIMEOUT_SECONDS` = 55s (`api/index.py:64`) — synthesis takes seconds.

### 2.2 Gemini TTS (opt-in, `TTS_PROVIDER=gemini`) — `gemini_tts()`, `api/index.py:1626-1673`

- Model: `GEMINI_TTS_MODEL` env var, default `gemini-2.5-flash-preview-tts` (`api/index.py:70`)
- Voices: `GEMINI_TTS_VOICE_A` / `GEMINI_TTS_VOICE_B`, default `Kore` / `Puck` (`api/index.py:73-74`), chosen by `request.speaker` (0/1)
- Auth: `x-goog-api-key` header, reuses `GEMINI_API_KEY`
- Batch generation: `_tts_batch_bounds()` (`api/index.py:1805-1824`) groups consecutive
  segments into ≤`GEMINI_TTS_BATCH_CHARS` batches; `gemini_tts_batch()`
  (`api/index.py:1827-1911`) builds one "SpeakerName: line" block per batch and uses
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
browsers can't play directly, so `pcm_to_wav()` (`api/index.py:1566-1580`) wraps it in a WAV
header (sample rate parsed from the mimeType). **Output:** `audio/wav` bytes.

### 2.3 ElevenLabs (opt-in, `TTS_PROVIDER=elevenlabs`) — `elevenlabs_tts()`, `api/index.py:1583-1623`

- Base URL: `ELEVENLABS_API_BASE`, default `https://api.elevenlabs.io/v1`; model `ELEVENLABS_MODEL`, default `eleven_multilingual_v2`
- Auth: `xi-api-key` header, key from `ELEVENLABS_API_KEY`
- Voices resolved from the account via `resolve_voice_ids()` (`api/index.py:343-372`; avoids the free-tier 402 on library voices), cached in-process (`_cached_voice_ids`, `api/index.py:340`); `ELEVENLABS_VOICE_HOST_A/B` override when both set

```
POST {ELEVENLABS_API_BASE}/text-to-speech/{voice_id}?output_format=mp3_44100_128
Header: xi-api-key: <ELEVENLABS_API_KEY>

{ "text": "<line, ≤1000 chars — MAX_SEGMENT_TEXT_CHARS, api/index.py:89>",
  "model_id": "eleven_multilingual_v2",
  "voice_settings": { "stability": 0.5, "similarity_boost": 0.75 } }
```

**Output:** `audio/mpeg` bytes.

**Input to the endpoint — `SegmentAudioRequest`, `api/index.py:279-286`:**

```json
{ "text": "string", "speaker": 0, "document_id": "string | null", "segment_index": 0 }
```

---

## 3. Firebase Authentication

Gates uploading, chat, regeneration and podcast audio behind sign-in; identifies the user
for storage and usage limits.

- **Backend:** `require_user()` (`api/index.py:427-449`) — FastAPI dependency (`Depends(require_user)`). Reads `Authorization: Bearer <idToken>`, verifies via `firebase_auth.verify_id_token()`, enforces the `ALLOWED_EMAILS` allowlist (403), returns `AuthedUser {uid, email}` (`api/index.py:293-295`). Admin init: `get_firebase_app()` (`api/index.py:381-402`).
- **Frontend:** `src/firebase.js` inits the client SDK. Sign-in `signInWithEmailAndPassword` (`src/App.jsx:138`); session watch `onAuthStateChanged` (`src/App.jsx:204`); `authedFetch()` (`src/App.jsx:206`) attaches `auth.currentUser.getIdToken()` (`src/App.jsx:207`) as a Bearer token on every call.

---

## 4. Firebase Firestore (Admin SDK)

Storage only — no LLM/TTS cost (the regenerate endpoints do call Gemini, but that cost is
the Gemini call, not the Firestore write). Client: `get_firestore_client()`
(`api/index.py:408-424`). Layout under `users/{uid}/documents/{doc_id}`:

| Path | Written by | File/line | Contents |
|---|---|---|---|
| `documents/{doc_id}` | `analyze_pdf()` | `api/index.py:1219` | `title`, `file_name`, `summary`, `quiz`, `podcast` (active script), `podcast_style` (active style), `podcast_versions` (`{style: script + audio_ns}` — every generated style version, ≤4,500 chars each, reused on style switch per §1.7), `document_context` (≤`MAX_STORED_CONTEXT_BYTES` = 900 KB, `api/index.py:102`), `created_at`. `summary`/`quiz` are overwritten in place by §1.5–1.6 |
| `documents/{doc_id}/audio/{style}.{segment_index}` | `save_segment_audio()` | `api/index.py:528` | `{ "data": "<base64 audio>", "mime": "audio/wav" \| "audio/mpeg", "chunks": N }` — one doc per segment, **namespaced per podcast style** (`_audio_doc_id()`, `api/index.py:463`) so every generated style keeps its own audio; pre-versioning audio lives under plain integer IDs (the `"legacy"` namespace, still served). Audio over `MAX_CACHED_AUDIO_BYTES` = 740 KB raw (`api/index.py:88`) is split across sibling chunk docs `….c{n}` (`{ "data": ... }` only) and reassembled on read by `get_cached_segment_audio()` (`api/index.py:502`); a missing chunk reads as a cache miss. Fresh regeneration of a style clears only that style's namespace (§1.7); document deletion drops the whole subcollection |
| `documents/{doc_id}/chat/log` | `save_chat_log()` | `api/index.py:1345` | `{ "messages": [...] }` — last `MAX_STORED_CHAT_MESSAGES` = 60, each text ≤`MAX_STORED_CHAT_TEXT_BYTES` = 10 KB (`api/index.py:98-99`) |
| `documents/{doc_id}/quiz_attempts/{auto_id}` | `save_quiz_attempt()` | `api/index.py:575-608` | `{ questions, answers, score, total, created_at }` — score computed server-side; capped at `MAX_QUIZ_ATTEMPTS` = 20 (`api/index.py:105`) |
| `usage/{yyyy-mm-dd}` | `increment_usage()` | `api/index.py:674-679` | `{ count, date }` — shared daily counter across analyze/chat/quiz-/summary-/podcast-regenerate/audio-generate |

Reads: `list_documents()` (`api/index.py:1119`), `get_document()` (`api/index.py:1149`),
`get_cached_segment_audio()` (`api/index.py:502`, returns bytes + MIME; legacy docs without
`mime` default to `audio/mpeg`), `list_cached_segment_indices()` (`api/index.py:636-657`),
`get_chat_log()` (`api/index.py:1331`), `list_quiz_attempts()` (`api/index.py:611-635`).
Deletes cascade to `audio`/`chat`/`quiz_attempts` via `_delete_document_and_subcollections()`
(`api/index.py:1170-1180`). Two small shared helpers back the regenerate endpoints:
`_get_document_or_404()` (`api/index.py:1421-1427`) and `_require_document_context()`
(`api/index.py:1430-1437`).

---

## Internal REST API

| Method | Path | Auth | Handler | External API |
|---|---|---|---|---|
| GET | `/api/health` | none | `api/index.py:1079` | — (reports `tts_provider`) |
| GET | `/api/profile` | required | `api/index.py:1096` | Firestore |
| GET | `/api/documents` | required | `api/index.py:1119` | Firestore |
| GET | `/api/documents/{doc_id}` | required | `api/index.py:1149` | Firestore |
| DELETE | `/api/documents/{doc_id}` | required | `api/index.py:1183` | Firestore |
| DELETE | `/api/documents` | required | `api/index.py:1192` | Firestore |
| POST | `/api/pdf/prepare` | none | `api/index.py:1201` | — |
| POST | `/api/pdf/analyze` | required | `api/index.py:1219` | Gemini, Firestore |
| POST | `/api/chat` | required | `api/index.py:1297` | Gemini |
| GET | `/api/documents/{doc_id}/chat` | required | `api/index.py:1331` | Firestore |
| PUT | `/api/documents/{doc_id}/chat` | required | `api/index.py:1345` | Firestore |
| GET | `/api/documents/{doc_id}/quiz/attempts` | required | `api/index.py:1362` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/attempts` | required | `api/index.py:1367` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/regenerate` | required | `api/index.py:1378` | Gemini, Firestore |
| POST | `/api/documents/{doc_id}/summary/regenerate` | required | `api/index.py:1440` | Gemini, Firestore |
| POST | `/api/documents/{doc_id}/podcast/regenerate` | required | `api/index.py:1482` | Gemini, Firestore |
| GET | `/api/podcast/audio-status/{doc_id}` | required | `api/index.py:1550` | Firestore |
| POST | `/api/podcast/segment-audio` | required | `api/index.py:1913` | Google Cloud TTS (whole episode, 1 call) **or** Gemini TTS (≤2,250-char batches) **or** ElevenLabs (1 call/segment) — on cache miss only — plus Firestore |

"Required" auth means `Depends(require_user)` — see §3.
