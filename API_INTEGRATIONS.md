# API Integrations

Reference for every external API this app calls: where the integration lives in code,
exactly what prompt/request is sent, and the input/output shape. All backend code is in
`api/index.py`; all frontend call sites are in `src/App.jsx` unless noted.

For deployment/env-var setup, see [README.md](README.md). This file is about *what* is
sent to each API and *where* in the code, not how to configure keys.

---

## 1. Google Gemini (`generativelanguage.googleapis.com`)

Used for three things: turning an uploaded PDF into structured study content, answering
Tutor chat questions scoped to that document, and generating a fresh, non-repeating quiz
on demand.

- Base URL: `GEMINI_API_BASE` env var, default `https://generativelanguage.googleapis.com/v1beta`
- Model: `GEMINI_MODEL` env var, default `gemini-2.5-flash`
- Auth: `x-goog-api-key` header, key from `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
- Shared transport function: `call_gemini()` — `api/index.py:646-694`

### 1.1 Shared transport — `call_gemini()`

**File/line:** `api/index.py:646`

```python
async def call_gemini(system_instruction: str, contents: list[dict[str, Any]], *, json_response: bool = True) -> str
```

**Request built** (`api/index.py:657-670`):

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

**Response parsed** (`api/index.py:685-694`): reads
`candidates[0].content.parts[*].text`, concatenates, and returns it as a plain string.
Raises `HTTPException(502)` on a non-200 status, an unexpected response shape, or an
empty completion (likely safety-blocked).

### 1.2 Study analysis (summary + quiz + podcast script)

**Endpoint:** `POST /api/pdf/analyze` — handler at `api/index.py:979-1035`
**Frontend call site:** `src/App.jsx:328` (inside the upload flow)

**Prompt — `STUDY_SYSTEM_INSTRUCTION`, `api/index.py:711-737`:**

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

**User content sent** (`api/index.py:987-1000`):

```
File name: {file_name}

Extracted PDF content:

{context}   # extracted PDF text, truncated to MAX_GEMINI_CONTEXT_CHARS = 400,000 chars (api/index.py:35)
```

Called as: `call_gemini(STUDY_SYSTEM_INSTRUCTION, contents, json_response=True)` — `api/index.py:1002`.

**Input to the endpoint** (multipart form — `api/index.py:980`):
`file: UploadFile` (PDF, ≤4 MB, enforced by `read_pdf_upload()` at `api/index.py:822-841`), plus
`Authorization: Bearer <Firebase ID token>` header.

**Output — `StudyAnalysisResponse`, `api/index.py:140-153`:**

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
(`api/index.py:783-819`), which delegates quiz parsing to the shared
`parse_quiz_questions()` helper (`api/index.py:757-780`, see §1.4), and is validated/parsed
by `parse_json_text()` (`api/index.py:697-708`).

### 1.3 Tutor chat

**Endpoint:** `POST /api/chat` — handler at `api/index.py:1038-1069`
**Frontend call site:** `src/App.jsx:1101` (inside `TutorPanel`'s `send()`)

**Prompt (built per-request), `api/index.py:1050-1057`:**

```
You are a friendly study tutor. Answer questions using ONLY the uploaded document below. If a question cannot be answered from the document, reply: 'Please ask a question related to the uploaded PDF.' Keep answers concise and clear.

File name: {request.file_name}

Document content:

{context}   # document_context from the analyze response, truncated to MAX_GEMINI_CONTEXT_CHARS
```

Conversation history (last 20 turns, `api/index.py:1060-1065`) is passed as Gemini `contents`
turns (`role: "user" | "model"`), with the new question appended last. Called as
`call_gemini(system_instruction, contents, json_response=False)` — plain text answer, not JSON.

**Input — `ChatRequest`, `api/index.py:161-165`:**

```json
{
  "document_context": "string (full extracted PDF text)",
  "question": "string",
  "file_name": "uploaded-document.pdf",
  "history": [ { "role": "user" | "tutor", "text": "string" } ]
}
```

**Output — `ChatResponse`, `api/index.py:168-169`:**

```json
{ "answer": "string" }
```

### 1.4 Quiz regeneration ("New questions")

**Endpoint:** `POST /api/documents/{doc_id}/quiz/regenerate` — handler at `api/index.py:1119-1169`
**Frontend call site:** `src/App.jsx:669` (`QuizPanel`'s `regenerate()`)

Generates a fresh set of quiz questions from the document's already-stored text — no
re-upload needed — and explicitly asks Gemini to avoid repeating recent questions, so
"New questions" produces a genuinely different set rather than a reshuffle of the same one.

**Prompt — `QUIZ_SYSTEM_INSTRUCTION`, `api/index.py:740-754`:**

```
You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
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
different questions, ideally covering different parts of the document. Everything must be grounded in the document content.
```

**Avoid-list construction** (`api/index.py:1138-1145`): the current quiz's question text
(from the stored document) plus the questions from the caller's last 5 quiz attempts
(`list_quiz_attempts()`, §4), deduped and capped to `MAX_AVOID_QUESTIONS` = 30
(`api/index.py:61`).

**User content sent** (`api/index.py:1147-1161`):

```
File name: {file_name}

Questions already used (avoid repeating these or close variants):
- <question text>
- ...

Document content:

{context}   # document_context stored on the document, truncated to MAX_GEMINI_CONTEXT_CHARS
```

Called as: `call_gemini(QUIZ_SYSTEM_INSTRUCTION, contents, json_response=True)` —
`api/index.py:1162`. The response is parsed with the same `parse_quiz_questions()` helper
used by study analysis (`api/index.py:757-780`).

**Input:** no request body — `doc_id` in the path plus the `Authorization` header. Requires
the document to exist and have `document_context` saved (400 if not — mirrors the Tutor
chat "re-upload" case).

**Output — `QuizRegenerateResponse`, `api/index.py:203-204`:**

```json
{ "quiz": [ { "q": "string", "options": ["string", "..."], "answer": 0, "topic": "string", "explanation": "string" } ] }
```

On success, the document's stored `quiz` field is overwritten with the new set
(`api/index.py:1167`) so reopening the document later shows the latest quiz — while past
*attempts* (§4) are kept exactly as they were taken, unaffected by regeneration.

---

## 2. ElevenLabs (`api.elevenlabs.io`)

Used to turn each podcast transcript line into spoken audio with two distinct host voices.

- Base URL: `ELEVENLABS_API_BASE` env var, default `https://api.elevenlabs.io/v1`
- Model: `ELEVENLABS_MODEL` env var, default `eleven_multilingual_v2`
- Auth: `xi-api-key` header, key from `ELEVENLABS_API_KEY`

### 2.1 Voice resolution — `resolve_voice_ids()`

**File/line:** `api/index.py:263-292`

Free-tier ElevenLabs accounts get a 402 if called with a voice ID not already in their own
account (e.g. hardcoded "Rachel"/"Adam" IDs), so voices are resolved from the account itself:

```
GET {ELEVENLABS_API_BASE}/voices
Header: xi-api-key: <ELEVENLABS_API_KEY>
```

Takes the first two voices in the account's list as (host A, host B) and caches the pair
in-process (`_cached_voice_ids`, `api/index.py:260`). `ELEVENLABS_VOICE_HOST_A` /
`ELEVENLABS_VOICE_HOST_B` env vars override this with explicit voice IDs when both are set.

### 2.2 Segment text-to-speech

**Endpoint:** `POST /api/podcast/segment-audio` — handler at `api/index.py:1182-1237`
**Frontend call site:** `src/App.jsx:864` (`PodcastPanel`'s `ensureSegmentUrl()`)

Cache check happens first — if `document_id` + `segment_index` are given and audio for
that exact segment was already generated, it's returned from Firestore with no ElevenLabs
call. See §4.

**Request sent on a cache miss:**

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

**Input — `SegmentAudioRequest`, `api/index.py:207-214`:**

```json
{
  "text": "string (one transcript line)",
  "speaker": 0,
  "document_id": "string | null (cache key)",
  "segment_index": 0
}
```

**Output:** raw `audio/mpeg` bytes (an MP3 clip), not JSON —
`Response(content=audio_bytes, media_type="audio/mpeg")` (cache hit, early in the handler;
cache miss, at the end after generating).

---

## 3. Firebase Authentication

Used to gate uploading, chat, quiz regeneration and podcast audio behind sign-in, and to
identify the user for per-account storage/usage limits.

### 3.1 Backend — verifying the caller

**File/line:** `require_user()`, `api/index.py:347-369` — a FastAPI dependency injected into
every protected route (`Depends(require_user)`).

- Reads the `Authorization: Bearer <idToken>` header.
- Verifies the token with `firebase_auth.verify_id_token(token, app=get_firebase_app())` (`api/index.py:361`) — the Firebase Admin SDK, no network round trip to a token-introspection endpoint.
- If `ALLOWED_EMAILS` is set, rejects any verified email not in that allowlist with 403 (`api/index.py:366-367`) — the actual access boundary, since the public web API key alone can't be used to bypass this.
- Returns `AuthedUser { uid, email }` (`api/index.py:221-223`) to the route.

Admin app init (service account or emulator) — `get_firebase_app()`, `api/index.py:301-326`.

### 3.2 Frontend — signing in and attaching tokens

**File:** `src/firebase.js` — initializes the Firebase client SDK (`initializeApp`, `getAuth`) from `VITE_FIREBASE_*` env vars (public, safe to expose).

- Sign-in: `signInWithEmailAndPassword(auth, email, password)` — `src/App.jsx:137` (`AuthScreen`'s `submit()`). No public sign-up form; accounts are created manually in the Firebase console.
- Session watch: `onAuthStateChanged(auth, setUser)` — `src/App.jsx:203`.
- Every authenticated API call goes through `authedFetch()` (`src/App.jsx:205-216`), which calls `auth.currentUser.getIdToken()` (`src/App.jsx:206`) and attaches it as `Authorization: Bearer <token>`.

---

## 4. Firebase Firestore (Admin SDK)

Storage only — no LLM/TTS calls, so nothing here counts against `DAILY_USAGE_LIMIT` (the
one exception is the quiz *regenerate* endpoint in §1.4, which calls Gemini and does count).
Client: `get_firestore_client()`, `api/index.py:328-347` (talks to the real project, or the
Local Emulator Suite when `FIRESTORE_EMULATOR_HOST` is set).

Collection layout, all under `users/{uid}/documents/{doc_id}`:

| Path | Written by | File/line | Contents |
|---|---|---|---|
| `documents/{doc_id}` | `analyze_pdf()` | `api/index.py:1013-1023` | `title`, `file_name`, `summary`, `quiz`, `podcast`, `document_context` (truncated to `MAX_STORED_CONTEXT_BYTES` = 900,000 bytes, `api/index.py:57`), `created_at`. `quiz` is later overwritten in place by `regenerate_quiz()` (`api/index.py:1167`) |
| `documents/{doc_id}/audio/{segment_index}` | `save_segment_audio()` | `api/index.py:405-415` | `{ "data": "<base64 mp3 bytes>" }` — one Firestore doc per podcast segment |
| `documents/{doc_id}/chat/log` | `save_chat_log()` | `api/index.py:1086-1100` | `{ "messages": [{ "role", "text" }, ...] }` — last `MAX_STORED_CHAT_MESSAGES` = 60 messages, each text truncated to `MAX_STORED_CHAT_TEXT_BYTES` = 10,000 bytes (`api/index.py:53-54`) |
| `documents/{doc_id}/quiz_attempts/{auto_id}` | `save_quiz_attempt()` | `api/index.py:438-470` | `{ "questions": [...], "answers": [...], "score", "total", "created_at" }` — one doc per submitted attempt; score is computed server-side from each question's own correct-answer index, never trusted from the client. Bounded to the most recent `MAX_QUIZ_ATTEMPTS` = 20 attempts (`api/index.py:60`), oldest deleted on write |
| `usage/{yyyy-mm-dd}` | `increment_usage()` | `api/index.py:536-541` | `{ "count": N, "date": "..." }` — shared daily counter across analyze/chat/quiz-regenerate/audio-generate |

Reads:

- List history (metadata only, no `document_context`): `list_documents()`, `api/index.py:881-908` → `GET /api/documents`
- One document (includes `document_context`): `get_document()`, `api/index.py:911-927` → `GET /api/documents/{doc_id}`
- Cached segment audio: `get_cached_segment_audio()`, `api/index.py:394-402`
- Which segments are cached (doc-id projection only, no audio bytes downloaded): `list_cached_segment_indices()`, `api/index.py:499-520` → `GET /api/podcast/audio-status/{doc_id}`
- Saved chat log: `get_chat_log()`, `api/index.py:1072-1083` → `GET /api/documents/{doc_id}/chat`
- Quiz attempt history (most recent `MAX_QUIZ_ATTEMPTS`, newest first): `list_quiz_attempts()`, `api/index.py:474-496` → `GET /api/documents/{doc_id}/quiz/attempts`

Deletes (`_delete_document_and_subcollections()`, `api/index.py:930-940`) cascade to the
`audio`, `chat` and `quiz_attempts` subcollections before deleting the parent document —
Firestore doesn't cascade-delete subcollections on its own.

---

## Internal REST API (frontend ↔ backend contract)

Full surface exposed by `api/index.py` (all under `/api`), for reference:

| Method | Path | Auth | Handler (file:line) | Calls external API |
|---|---|---|---|---|
| GET | `/api/health` | none | `api/index.py:843` | — |
| GET | `/api/profile` | required | `api/index.py:858` | Firestore |
| GET | `/api/documents` | required | `api/index.py:882` | Firestore |
| GET | `/api/documents/{doc_id}` | required | `api/index.py:912` | Firestore |
| DELETE | `/api/documents/{doc_id}` | required | `api/index.py:944` | Firestore |
| DELETE | `/api/documents` | required | `api/index.py:953` | Firestore |
| POST | `/api/pdf/prepare` | none | `api/index.py:962` | — (chunking/preview only, no Gemini call) |
| POST | `/api/pdf/analyze` | required | `api/index.py:980` | Gemini, Firestore |
| POST | `/api/chat` | required | `api/index.py:1039` | Gemini |
| GET | `/api/documents/{doc_id}/chat` | required | `api/index.py:1073` | Firestore |
| PUT | `/api/documents/{doc_id}/chat` | required | `api/index.py:1087` | Firestore |
| GET | `/api/documents/{doc_id}/quiz/attempts` | required | `api/index.py:1104` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/attempts` | required | `api/index.py:1109` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/regenerate` | required | `api/index.py:1120` | Gemini, Firestore |
| GET | `/api/podcast/audio-status/{doc_id}` | required | `api/index.py:1172` | Firestore |
| POST | `/api/podcast/segment-audio` | required | `api/index.py:1182` | ElevenLabs (on cache miss), Firestore |

"Required" auth means `Depends(require_user)` — see §3.1.
