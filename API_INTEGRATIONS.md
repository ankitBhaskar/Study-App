# API Integrations

Reference for every external API this app calls: where the integration lives in code,
exactly what prompt/request is sent, and the input/output shape. All backend code is in
`api/index.py`; all frontend call sites are in `src/App.jsx` unless noted.

For deployment/env-var setup, see [README.md](README.md). This file is about *what* is
sent to each API and *where* in the code, not how to configure keys.

---

## 1. Google Gemini (`generativelanguage.googleapis.com`)

Used for two things: turning an uploaded PDF into structured study content, and answering
Tutor chat questions scoped to that document.

- Base URL: `GEMINI_API_BASE` env var, default `https://generativelanguage.googleapis.com/v1beta`
- Model: `GEMINI_MODEL` env var, default `gemini-2.5-flash`
- Auth: `x-goog-api-key` header, key from `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
- Shared transport function: `call_gemini()` — `api/index.py:549-597`

### 1.1 Shared transport — `call_gemini()`

**File/line:** `api/index.py:549`

```python
async def call_gemini(system_instruction: str, contents: list[dict[str, Any]], *, json_response: bool = True) -> str
```

**Request built** (`api/index.py:560-573`):

```json
POST {GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent
Header: x-goog-api-key: <GEMINI_API_KEY>

{
  "systemInstruction": { "parts": [{ "text": "<system_instruction>" }] },
  "contents": [ { "role": "user" | "model", "parts": [{ "text": "..." }] }, ... ],
  "generationConfig": {
    "temperature": 0.3,
    "topP": 0.9,
    "maxOutputTokens": 16384,
    "responseMimeType": "application/json"   // only when json_response=True
  }
}
```

**Response parsed** (`api/index.py:588-597`): reads
`candidates[0].content.parts[*].text`, concatenates, and returns it as a plain string.
Raises `HTTPException(502)` on a non-200 status, an unexpected response shape, or an
empty completion (likely safety-blocked).

### 1.2 Study analysis (summary + quiz + podcast script)

**Endpoint:** `POST /api/pdf/analyze` — handler at `api/index.py:857-913`
**Frontend call site:** `src/App.jsx:328` (inside `analyzeDocument`/upload flow)

**Prompt — `STUDY_SYSTEM_INSTRUCTION`, `api/index.py:614-640`:**

```
You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Create study material and return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{
  "title": "short document title, e.g. chapter name",
  "summary": ["4 to 6 key-point strings covering the document"],
  "quiz": {
    "questions": [
      {
        "question": "string",
        "options": ["exactly 4 answer options"],
        "correctOptionIndex": 0,
        "explanation": "why the answer is correct",
        "topic": "short topic label"
      }
    ]
  },
  "podcastScript": {
    "title": "episode title",
    "durationMinutes": 10,
    "hosts": ["Maya", "Theo"],
    "segments": [
      {"timestamp": "0:00", "speaker": "Maya", "line": "spoken line"}
    ]
  }
}
Create 3 to 5 quiz questions. Create 8 to 12 podcast segments as a natural two-host conversation walking through the document,
with timestamps spread between 0:00 and 9:30 in mm:ss format. Everything must be grounded in the document content.
```

**User content sent** (`api/index.py:865-878`):

```
File name: {file_name}

Extracted PDF content:

{context}   # extracted PDF text, truncated to MAX_GEMINI_CONTEXT_CHARS = 400,000 chars (api/index.py:35)
```

Called as: `call_gemini(STUDY_SYSTEM_INSTRUCTION, contents, json_response=True)` — `api/index.py:880`.

**Input to the endpoint** (multipart form, `PdfChunk`/upload — `api/index.py:858`):
`file: UploadFile` (PDF, ≤4 MB, enforced by `read_pdf_upload()` at `api/index.py:704`), plus
`Authorization: Bearer <Firebase ID token>` header.

**Output — `StudyAnalysisResponse`, `api/index.py:136-149`:**

```json
{
  "file_name": "string",
  "page_count": 0,
  "title": "string",
  "summary": ["string", "..."],
  "quiz": [
    { "q": "string", "options": ["string", "..."], "answer": 0, "topic": "string", "explanation": "string" }
  ],
  "podcast": {
    "duration": "10:00",
    "hosts": ["Maya", "Theo"],
    "transcript": [ { "t": "0:00", "who": "Maya", "line": "string" } ]
  },
  "document_context": "string (extracted PDF text, echoed back so the client can send it with chat calls)",
  "document_id": "string | null (Firestore doc id, null if Firestore isn't configured)"
}
```

Gemini's raw JSON is normalised into this shape by `normalise_study_content()`
(`api/index.py:643-702`) and validated/parsed by `parse_json_text()` (`api/index.py:600-611`).

### 1.3 Tutor chat

**Endpoint:** `POST /api/chat` — handler at `api/index.py:916-946`
**Frontend call site:** `src/App.jsx:1024` (inside `TutorPanel`'s `send()`)

**Prompt (built per-request), `api/index.py:928-935`:**

```
You are a friendly study tutor. Answer questions using ONLY the uploaded document below. If a question cannot be answered from the document, reply: 'Please ask a question related to the uploaded PDF.' Keep answers concise and clear.

File name: {request.file_name}

Document content:

{context}   # document_context from the analyze response, truncated to MAX_GEMINI_CONTEXT_CHARS
```

Conversation history (last 20 turns, `api/index.py:938-943`) is passed as Gemini `contents`
turns (`role: "user" | "model"`), with the new question appended last. Called as
`call_gemini(system_instruction, contents, json_response=False)` — plain text answer, not JSON.

**Input — `ChatRequest`, `api/index.py:157-161`:**

```json
{
  "document_context": "string (full extracted PDF text)",
  "question": "string",
  "file_name": "uploaded-document.pdf",
  "history": [ { "role": "user" | "tutor", "text": "string" } ]
}
```

**Output — `ChatResponse`, `api/index.py:164-165`:**

```json
{ "answer": "string" }
```

---

## 2. ElevenLabs (`api.elevenlabs.io`)

Used to turn each podcast transcript line into spoken audio with two distinct host voices.

- Base URL: `ELEVENLABS_API_BASE` env var, default `https://api.elevenlabs.io/v1`
- Model: `ELEVENLABS_MODEL` env var, default `eleven_multilingual_v2`
- Auth: `xi-api-key` header, key from `ELEVENLABS_API_KEY`

### 2.1 Voice resolution — `resolve_voice_ids()`

**File/line:** `api/index.py:237-266`

Free-tier ElevenLabs accounts get a 402 if called with a voice ID not already in their own
account (e.g. hardcoded "Rachel"/"Adam" IDs), so voices are resolved from the account itself:

```
GET {ELEVENLABS_API_BASE}/voices
Header: xi-api-key: <ELEVENLABS_API_KEY>
```

Takes the first two voices in the account's list as (host A, host B) and caches the pair
in-process (`_cached_voice_ids`, `api/index.py:234`). `ELEVENLABS_VOICE_HOST_A` /
`ELEVENLABS_VOICE_HOST_B` env vars override this with explicit voice IDs when both are set.

### 2.2 Segment text-to-speech

**Endpoint:** `POST /api/podcast/segment-audio` — handler at `api/index.py:991-1046`
**Frontend call site:** `src/App.jsx:764` (`PodcastPanel`'s `ensureSegmentUrl()`)

Cache check happens first (`api/index.py:995-999`) — if `document_id` + `segment_index` are
given and audio for that exact segment was already generated, it's returned from Firestore
with no ElevenLabs call. See §4.2.

**Request sent on a cache miss** (`api/index.py:1019-1034`):

```
POST {ELEVENLABS_API_BASE}/text-to-speech/{voice_id}?output_format=mp3_44100_128
Header: xi-api-key: <ELEVENLABS_API_KEY>

{
  "text": "<one transcript line, ≤1000 chars — MAX_SEGMENT_TEXT_CHARS, api/index.py:50>",
  "model_id": "eleven_multilingual_v2",
  "voice_settings": { "stability": 0.5, "similarity_boost": 0.75 }
}
```

`voice_id` is host A's or host B's resolved voice, chosen by `request.speaker` (0 or 1).

**Input — `SegmentAudioRequest`, `api/index.py:181-188`:**

```json
{
  "text": "string (one transcript line)",
  "speaker": 0,
  "document_id": "string | null (cache key)",
  "segment_index": 0
}
```

**Output:** raw `audio/mpeg` bytes (an MP3 clip), not JSON — `Response(content=audio_bytes, media_type="audio/mpeg")` at `api/index.py:1046` (cache hit) / end of the same handler (cache miss).

---

## 3. Firebase Authentication

Used to gate uploading, chat, and podcast audio behind sign-in, and to identify the user
for per-account storage/usage limits.

### 3.1 Backend — verifying the caller

**File/line:** `require_user()`, `api/index.py:321-343` — a FastAPI dependency injected into
every protected route (`Depends(require_user)`).

- Reads the `Authorization: Bearer <idToken>` header.
- Verifies the token with `firebase_auth.verify_id_token(token, app=get_firebase_app())` (`api/index.py:335`) — the Firebase Admin SDK, no network prompt/text involved.
- If `ALLOWED_EMAILS` is set, rejects any verified email not in that allowlist with 403 (`api/index.py:340-341`) — the actual access boundary, since the public web API key alone can't be used to bypass this.
- Returns `AuthedUser { uid, email }` (`api/index.py:195-197`) to the route.

Admin app init (service account or emulator) — `get_firebase_app()`, `api/index.py:275-296`.

### 3.2 Frontend — signing in and attaching tokens

**File:** `src/firebase.js` — initializes the Firebase client SDK (`initializeApp`, `getAuth`) from `VITE_FIREBASE_*` env vars (public, safe to expose).

- Sign-in: `signInWithEmailAndPassword(auth, email, password)` — `src/App.jsx:137` (`AuthScreen`'s `submit()`). No public sign-up form; accounts are created manually in the Firebase console.
- Session watch: `onAuthStateChanged(auth, setUser)` — `src/App.jsx:203`.
- Every authenticated API call goes through `authedFetch()` (`src/App.jsx:205-216`), which calls `auth.currentUser.getIdToken()` (`src/App.jsx:206`) and attaches it as `Authorization: Bearer <token>`.

---

## 4. Firebase Firestore (Admin SDK)

Storage only — no LLM/TTS calls, so nothing here counts against `DAILY_USAGE_LIMIT`. Client:
`get_firestore_client()`, `api/index.py:302-318` (talks to the real project, or the Local
Emulator Suite when `FIRESTORE_EMULATOR_HOST` is set).

Collection layout, all under `users/{uid}/documents/{doc_id}`:

| Path | Written by | File/line | Contents |
|---|---|---|---|
| `documents/{doc_id}` | `analyze_pdf()` | `api/index.py:891-901` | `title`, `file_name`, `summary`, `quiz`, `podcast`, `document_context` (truncated to `MAX_STORED_CONTEXT_BYTES` = 900,000 bytes, `api/index.py:57`), `created_at` |
| `documents/{doc_id}/audio/{segment_index}` | `save_segment_audio()` | `api/index.py:379-389` | `{ "data": "<base64 mp3 bytes>" }` — one Firestore doc per podcast segment |
| `documents/{doc_id}/chat/log` | `save_chat_log()` | `api/index.py:964-979` | `{ "messages": [{ "role", "text" }, ...] }` — last `MAX_STORED_CHAT_MESSAGES` = 60 messages, each text truncated to `MAX_STORED_CHAT_TEXT_BYTES` = 10,000 bytes (`api/index.py:53-54`) |
| `usage/{yyyy-mm-dd}` | `increment_usage()` | `api/index.py:439-444` | `{ "count": N, "date": "..." }` — shared daily counter across analyze/chat/audio-generate |

Reads:

- List history (metadata only, no `document_context`): `list_documents()`, `api/index.py:764-791` → `GET /api/documents`
- One document (includes `document_context`): `get_document()`, `api/index.py:794-811` → `GET /api/documents/{doc_id}`
- Cached segment audio: `get_cached_segment_audio()`, `api/index.py:368-376`
- Which segments are cached (doc-id projection only, no audio bytes downloaded): `list_cached_segment_indices()`, `api/index.py:402-423` → `GET /api/podcast/audio-status/{doc_id}`
- Saved chat log: `get_chat_log()`, `api/index.py:950-962` → `GET /api/documents/{doc_id}/chat`

Deletes (`_delete_document_and_audio()`, `api/index.py:812-820`) cascade to the `audio` and
`chat` subcollections before deleting the parent document — Firestore doesn't cascade-delete
subcollections on its own.

---

## Internal REST API (frontend ↔ backend contract)

Full surface exposed by `api/index.py` (all under `/api`), for reference:

| Method | Path | Auth | Handler (file:line) | Calls external API |
|---|---|---|---|---|
| GET | `/api/health` | none | `api/index.py:725` | — |
| GET | `/api/profile` | required | `api/index.py:741` | Firestore |
| GET | `/api/documents` | required | `api/index.py:764` | Firestore |
| GET | `/api/documents/{doc_id}` | required | `api/index.py:794` | Firestore |
| DELETE | `/api/documents/{doc_id}` | required | `api/index.py:824` | Firestore |
| DELETE | `/api/documents` | required | `api/index.py:831` | Firestore |
| POST | `/api/pdf/prepare` | none | `api/index.py:840` | — (chunking/preview only, no Gemini call) |
| POST | `/api/pdf/analyze` | required | `api/index.py:858` | Gemini, Firestore |
| POST | `/api/chat` | required | `api/index.py:917` | Gemini |
| GET | `/api/documents/{doc_id}/chat` | required | `api/index.py:951` | Firestore |
| PUT | `/api/documents/{doc_id}/chat` | required | `api/index.py:965` | Firestore |
| GET | `/api/podcast/audio-status/{doc_id}` | required | `api/index.py:982` | Firestore |
| POST | `/api/podcast/segment-audio` | required | `api/index.py:992` | ElevenLabs (on cache miss), Firestore |

"Required" auth means `Depends(require_user)` — see §3.1.
