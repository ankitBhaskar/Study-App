# API Integrations

Reference for every external API this app calls: where the integration lives in code,
exactly what prompt/request is sent, and the input/output shape. All backend code is in
`api/index.py`; all frontend call sites are in `src/App.jsx` unless noted.

For deployment/env-var setup, see [README.md](README.md). This file is about *what* is
sent to each API and *where* in the code, not how to configure keys.

---

## 1. Google Gemini (`generativelanguage.googleapis.com`)

Used for turning an uploaded PDF into structured study content, answering Tutor chat
questions scoped to that document, and regenerating the quiz, summary, or podcast script
individually on demand — each with selectable options (podcast style; summary length/focus).

- Base URL: `GEMINI_API_BASE` env var, default `https://generativelanguage.googleapis.com/v1beta`
- Model: `GEMINI_MODEL` env var, default `gemini-2.5-flash`
- Auth: `x-goog-api-key` header, key from `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
- Shared transport function: `call_gemini()` — `api/index.py:663-711`

### 1.1 Shared transport — `call_gemini()`

**File/line:** `api/index.py:663`

```python
async def call_gemini(system_instruction: str, contents: list[dict[str, Any]], *, json_response: bool = True) -> str
```

**Request built** (`api/index.py:674-687`):

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

**Response parsed** (`api/index.py:702-711`): reads
`candidates[0].content.parts[*].text`, concatenates, and returns it as a plain string.
Raises `HTTPException(502)` on a non-200 status, an unexpected response shape, or an
empty completion (likely safety-blocked).

### 1.2 Shared style/length guidance

**File/line:** `api/index.py:728-770` (`PODCAST_STYLES`, `SUMMARY_LENGTHS`,
`PODCAST_STYLE_GUIDANCE`, `SUMMARY_LENGTH_GUIDANCE`, `_summary_instruction_line()`)

The same guidance text backs both the combined study-analysis prompt (§1.3) and the
three standalone regenerate-only prompts (§1.5–1.7), so choosing a style/length produces
consistent output whether it's picked at upload time or afterward via "New script" /
"Regenerate summary".

**Podcast styles** (`PODCAST_STYLES = {"conversation", "solo", "interview"}`, invalid
values fall back to `"conversation"`):

| Style | Guidance sent to Gemini |
|---|---|
| `conversation` (default) | Two invented hosts (e.g. "Maya" and "Theo") who banter, ask each other questions, and alternate frequently. |
| `solo` | One invented host name, used as `"speaker"` for every segment — a flowing monologue. |
| `interview` | Two invented roles, "Host" and "Guest" (an expert), with the Host asking follow-up questions. |

**Summary lengths** (`SUMMARY_LENGTHS = {"concise", "detailed"}`, invalid values fall
back to `"concise"`):

| Length | Guidance sent to Gemini |
|---|---|
| `concise` (default) | 4 to 6 concise key-point strings. |
| `detailed` | 8 to 12 detailed key-point strings, going deeper into mechanisms, numbers and examples. |

An optional `focus` string (≤200 chars, both in the combined prompt and the standalone
summary-regenerate request) appends: `Focus specifically on this topic from the
document: "<focus>" — skip parts of the document unrelated to it.`

### 1.3 Study analysis (summary + quiz + podcast script, with options)

**Endpoint:** `POST /api/pdf/analyze` — handler at `api/index.py:1078-1140`
**Frontend call site:** `src/App.jsx:328` (inside the upload flow; the frontend currently
always sends the defaults — `conversation` / `concise` / no focus — the Form fields exist
so the same options used for regeneration can be wired to upload-time pickers later)

**Request:** multipart form (`api/index.py:1079-1086`) —
`file: UploadFile` (PDF, ≤4 MB, enforced by `read_pdf_upload()` at `api/index.py:921-939`),
`podcast_style: str = "conversation"`, `summary_length: str = "concise"`,
`summary_focus: str = ""` (all optional Form fields), plus
`Authorization: Bearer <Firebase ID token>` header.

**Prompt — `build_study_system_instruction()`, `api/index.py:772-800`:**

```
You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Create study material and return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{
  "title": "short document title, e.g. chapter name",
  "summary": ["key-point strings covering the document"],
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
    "durationMinutes": 10,
    "hosts": ["name", ...],
    "segments": [
      {"timestamp": "0:00", "speaker": "name", "line": "spoken line"}
    ]
  }
}
Summary instructions: {summary_line}
Podcast instructions: {podcast_line} Create 8 to 12 podcast segments with timestamps spread between 0:00 and 9:30 in mm:ss format.
Create 3 to 5 quiz questions. Everything must be grounded in the document content.
```

`{summary_line}` / `{podcast_line}` are substituted from the guidance tables in §1.2
based on the request's `summary_length`/`summary_focus`/`podcast_style`.

**User content sent** (`api/index.py:1097-1109`):

```
File name: {file_name}

Extracted PDF content:

{context}   # extracted PDF text, truncated to MAX_GEMINI_CONTEXT_CHARS = 400,000 chars (api/index.py:35)
```

Called as: `call_gemini(system_instruction, contents, json_response=True)` — `api/index.py:1112`.

**Output — `StudyAnalysisResponse`, `api/index.py:140-152`:**

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
    "hosts": ["name", "..."],
    "transcript": [ { "t": "0:00", "who": "name", "line": "string" } ]
  },
  "document_context": "string (extracted PDF text, echoed back so the client can send it with chat calls)",
  "document_id": "string | null (Firestore doc id, null if Firestore isn't configured)"
}
```

Gemini's raw JSON is normalised into this shape by `normalise_study_content()`
(`api/index.py:903-917`), which delegates to three shared parsers reused by the
regenerate endpoints too: `parse_summary_points()` (`api/index.py:871-874`),
`parse_quiz_questions()` (§1.6), and `parse_podcast_script()` (`api/index.py:877-896`).
Raw JSON is validated/parsed by `parse_json_text()` (`api/index.py:714-725`).

### 1.4 Tutor chat

**Endpoint:** `POST /api/chat` — handler at `api/index.py:1149-1180`
**Frontend call site:** `src/App.jsx:1244` (inside `TutorPanel`'s `send()`)

**Prompt (built per-request), `api/index.py:1161-1168`:**

```
You are a friendly study tutor. Answer questions using ONLY the uploaded document below. If a question cannot be answered from the document, reply: 'Please ask a question related to the uploaded PDF.' Keep answers concise and clear.

File name: {request.file_name}

Document content:

{context}   # document_context from the analyze response, truncated to MAX_GEMINI_CONTEXT_CHARS
```

Conversation history (last 20 turns, `api/index.py:1171-1176`) is passed as Gemini
`contents` turns (`role: "user" | "model"`), with the new question appended last. Called
as `call_gemini(system_instruction, contents, json_response=False)` — plain text answer,
not JSON.

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

### 1.5 Quiz regeneration ("New questions")

**Endpoint:** `POST /api/documents/{doc_id}/quiz/regenerate` — handler at `api/index.py:1230-1270`
**Frontend call site:** `src/App.jsx:735` (`QuizPanel`'s `regenerate()`)

**Prompt — `QUIZ_SYSTEM_INSTRUCTION`, `api/index.py:828-842`:**

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

**Avoid-list construction** (`api/index.py:1237-1244`): the current quiz's question text
plus the questions from the caller's last 5 quiz attempts (`list_quiz_attempts()`, §4),
deduped and capped to `MAX_AVOID_QUESTIONS` = 30 (`api/index.py:61`).

**Input:** no request body — `doc_id` in the path plus the `Authorization` header.
Requires the document to exist and have `document_context` saved (400 if not, via the
shared `_require_document_context()` helper, `api/index.py:1282-1289`).

**Output — `QuizRegenerateResponse`, `api/index.py:203-204`:**

```json
{ "quiz": [ { "q": "string", "options": ["string", "..."], "answer": 0, "topic": "string", "explanation": "string" } ] }
```

Parsed with `parse_quiz_questions()` (`api/index.py:845-865`). On success, the document's
stored `quiz` field is overwritten (`api/index.py:1268`) so reopening later shows the
latest quiz, while past *attempts* (§4) are kept exactly as taken.

### 1.6 Summary regeneration ("Regenerate summary")

**Endpoint:** `POST /api/documents/{doc_id}/summary/regenerate` — handler at `api/index.py:1292-1319`
**Frontend call site:** `src/App.jsx:608` (`SummaryPanel`'s `regenerate()`)

**Prompt — `build_summary_system_instruction()`, `api/index.py:804-810`:**

```
You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Generate a fresh summary of the document. Return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{
  "summary": ["key-point strings covering the document"]
}
{summary_line} Everything must be grounded in the document content.
```

`{summary_line}` comes from the length/focus guidance in §1.2.

**Input — `SummaryRegenerateRequest`, `api/index.py:207-209`:**

```json
{ "length": "concise" | "detailed", "focus": "string (optional, ≤200 chars)" }
```

**Output — `SummaryRegenerateResponse`, `api/index.py:212-213`:**

```json
{ "summary": ["string", "..."] }
```

Parsed with `parse_summary_points()` (`api/index.py:871-874`). On success, the document's
stored `summary` field is overwritten (`api/index.py:1317`).

### 1.7 Podcast script regeneration ("New script")

**Endpoint:** `POST /api/documents/{doc_id}/podcast/regenerate` — handler at `api/index.py:1327-1364`
**Frontend call site:** `src/App.jsx:902` (`PodcastPanel`'s `regenerateScript()`)

**Prompt — `build_podcast_system_instruction()`, `api/index.py:814-824`:**

```
You are an expert study assistant. Use ONLY the uploaded document content provided by the user.
Generate a fresh podcast script grounded in the document. Return a single JSON object with EXACTLY this shape (no markdown, no extra keys):
{
  "durationMinutes": 10,
  "hosts": ["name", ...],
  "segments": [
    {"timestamp": "0:00", "speaker": "name", "line": "spoken line"}
  ]
}
{podcast_line} Create 8 to 12 segments with timestamps spread between 0:00 and 9:30 in mm:ss format. Everything must be grounded in the document content.
```

`{podcast_line}` comes from the style guidance table in §1.2.

**Input — `PodcastRegenerateRequest`, `api/index.py:216-217`:**

```json
{ "style": "conversation" | "solo" | "interview" }
```

**Output — `PodcastRegenerateResponse`, `api/index.py:220-221`:**

```json
{ "podcast": { "duration": "10:00", "hosts": ["name", "..."], "transcript": [ { "t": "0:00", "who": "name", "line": "string" } ] } }
```

Parsed with `parse_podcast_script()` (`api/index.py:877-896`). On success
(`api/index.py:1356-1363`): any previously cached segment audio for the document is
**deleted** first — a new script's segments don't line up with old cached audio at the
same indices, so stale audio is dropped rather than risk mismatched playback — then the
document's stored `podcast` field is overwritten.

---

## 2. ElevenLabs (`api.elevenlabs.io`)

Used to turn each podcast transcript line into spoken audio with up to two distinct
voices (one for a solo-narrator script).

- Base URL: `ELEVENLABS_API_BASE` env var, default `https://api.elevenlabs.io/v1`
- Model: `ELEVENLABS_MODEL` env var, default `eleven_multilingual_v2`
- Auth: `xi-api-key` header, key from `ELEVENLABS_API_KEY`

### 2.1 Voice resolution — `resolve_voice_ids()`

**File/line:** `api/index.py:280-309`

Free-tier ElevenLabs accounts get a 402 if called with a voice ID not already in their own
account (e.g. hardcoded "Rachel"/"Adam" IDs), so voices are resolved from the account itself:

```
GET {ELEVENLABS_API_BASE}/voices
Header: xi-api-key: <ELEVENLABS_API_KEY>
```

Takes the first two voices in the account's list as (host A, host B) and caches the pair
in-process (`_cached_voice_ids`, `api/index.py:277`). `ELEVENLABS_VOICE_HOST_A` /
`ELEVENLABS_VOICE_HOST_B` env vars override this with explicit voice IDs when both are set.

### 2.2 Segment text-to-speech

**Endpoint:** `POST /api/podcast/segment-audio` — handler at `api/index.py:1377-1437`
**Frontend call site:** `src/App.jsx:983` (`PodcastPanel`'s `ensureSegmentUrl()`)

Cache check happens first — if `document_id` + `segment_index` are given and audio for
that exact segment was already generated, it's returned from Firestore with no ElevenLabs
call. See §4. (Regenerating the podcast script, §1.7, clears this cache for the document.)

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
For a solo-narrator script (one host), the frontend always sends `speaker: 0`.

**Input — `SegmentAudioRequest`, `api/index.py:224-231`:**

```json
{
  "text": "string (one transcript line)",
  "speaker": 0,
  "document_id": "string | null (cache key)",
  "segment_index": 0
}
```

**Output:** raw `audio/mpeg` bytes (an MP3 clip), not JSON.

---

## 3. Firebase Authentication

Used to gate uploading, chat, quiz/summary/podcast regeneration and podcast audio behind
sign-in, and to identify the user for per-account storage/usage limits.

### 3.1 Backend — verifying the caller

**File/line:** `require_user()`, `api/index.py:364-386` — a FastAPI dependency injected
into every protected route (`Depends(require_user)`).

- Reads the `Authorization: Bearer <idToken>` header.
- Verifies the token with `firebase_auth.verify_id_token(token, app=get_firebase_app())` (`api/index.py:378`) — the Firebase Admin SDK, no round trip to a token-introspection endpoint.
- If `ALLOWED_EMAILS` is set, rejects any verified email not in that allowlist with 403 (`api/index.py:383-384`) — the actual access boundary, since the public web API key alone can't be used to bypass this.
- Returns `AuthedUser { uid, email }` (`api/index.py:238-240`) to the route.

Admin app init (service account or emulator) — `get_firebase_app()`, `api/index.py:318-338`.

### 3.2 Frontend — signing in and attaching tokens

**File:** `src/firebase.js` — initializes the Firebase client SDK (`initializeApp`, `getAuth`) from `VITE_FIREBASE_*` env vars (public, safe to expose).

- Sign-in: `signInWithEmailAndPassword(auth, email, password)` — `src/App.jsx:137` (`AuthScreen`'s `submit()`). No public sign-up form; accounts are created manually in the Firebase console.
- Session watch: `onAuthStateChanged(auth, setUser)` — `src/App.jsx:203`.
- Every authenticated API call goes through `authedFetch()` (`src/App.jsx:205-216`), which calls `auth.currentUser.getIdToken()` (`src/App.jsx:206`) and attaches it as `Authorization: Bearer <token>`.

---

## 4. Firebase Firestore (Admin SDK)

Storage only — no LLM/TTS calls, so nothing here counts against `DAILY_USAGE_LIMIT`. (The
regenerate endpoints in §1.5–1.7 also write here, but their `DAILY_USAGE_LIMIT` cost comes
from the Gemini call, not the Firestore write.) Client: `get_firestore_client()`,
`api/index.py:345-361` (talks to the real project, or the Local Emulator Suite when
`FIRESTORE_EMULATOR_HOST` is set). Two small shared helpers used by the regenerate
endpoints: `_get_document_or_404()` and `_require_document_context()`
(`api/index.py:1273-1289`).

Collection layout, all under `users/{uid}/documents/{doc_id}`:

| Path | Written by | File/line | Contents |
|---|---|---|---|
| `documents/{doc_id}` | `analyze_pdf()` | `api/index.py:1113-1133` | `title`, `file_name`, `summary`, `quiz`, `podcast`, `document_context` (truncated to `MAX_STORED_CONTEXT_BYTES` = 900,000 bytes, `api/index.py:57`), `created_at`. `summary`/`quiz`/`podcast` are each later overwritten in place by the corresponding regenerate endpoint (§1.5–1.7) |
| `documents/{doc_id}/audio/{segment_index}` | `save_segment_audio()` | `api/index.py:422-431` | `{ "data": "<base64 mp3 bytes>" }` — one Firestore doc per podcast segment; the whole subcollection is deleted on podcast-script regeneration (§1.7) |
| `documents/{doc_id}/chat/log` | `save_chat_log()` | `api/index.py:1197-1212` | `{ "messages": [{ "role", "text" }, ...] }` — last `MAX_STORED_CHAT_MESSAGES` = 60 messages, each text truncated to `MAX_STORED_CHAT_TEXT_BYTES` = 10,000 bytes (`api/index.py:53-54`) |
| `documents/{doc_id}/quiz_attempts/{auto_id}` | `save_quiz_attempt()` | `api/index.py:455-488` | `{ "questions": [...], "answers": [...], "score", "total", "created_at" }` — one doc per submitted attempt; score is computed server-side from each question's own correct-answer index, never trusted from the client. Bounded to the most recent `MAX_QUIZ_ATTEMPTS` = 20 attempts (`api/index.py:60`), oldest deleted on write |
| `usage/{yyyy-mm-dd}` | `increment_usage()` | `api/index.py:553-558` | `{ "count": N, "date": "..." }` — shared daily counter across analyze/chat/quiz-regenerate/summary-regenerate/podcast-regenerate/audio-generate |

Reads:

- List history (metadata only, no `document_context`): `list_documents()`, `api/index.py:980-1008` → `GET /api/documents`
- One document (includes `document_context`): `get_document()`, `api/index.py:1010-1040` → `GET /api/documents/{doc_id}`
- Cached segment audio: `get_cached_segment_audio()`, `api/index.py:411-418`
- Which segments are cached (doc-id projection only, no audio bytes downloaded): `list_cached_segment_indices()`, `api/index.py:516-536` → `GET /api/podcast/audio-status/{doc_id}`
- Saved chat log: `get_chat_log()`, `api/index.py:1183-1195` → `GET /api/documents/{doc_id}/chat`
- Quiz attempt history (most recent `MAX_QUIZ_ATTEMPTS`, newest first): `list_quiz_attempts()`, `api/index.py:491-513` → `GET /api/documents/{doc_id}/quiz/attempts`

Deletes (`_delete_document_and_subcollections()`, `api/index.py:1029-1039`) cascade to the
`audio`, `chat` and `quiz_attempts` subcollections before deleting the parent document —
Firestore doesn't cascade-delete subcollections on its own.

---

## Internal REST API (frontend ↔ backend contract)

Full surface exposed by `api/index.py` (all under `/api`), for reference:

| Method | Path | Auth | Handler (file:line) | Calls external API |
|---|---|---|---|---|
| GET | `/api/health` | none | `api/index.py:942` | — |
| GET | `/api/profile` | required | `api/index.py:957` | Firestore |
| GET | `/api/documents` | required | `api/index.py:980` | Firestore |
| GET | `/api/documents/{doc_id}` | required | `api/index.py:1010` | Firestore |
| DELETE | `/api/documents/{doc_id}` | required | `api/index.py:1042` | Firestore |
| DELETE | `/api/documents` | required | `api/index.py:1051` | Firestore |
| POST | `/api/pdf/prepare` | none | `api/index.py:1060` | — (chunking/preview only, no Gemini call) |
| POST | `/api/pdf/analyze` | required | `api/index.py:1079` | Gemini, Firestore |
| POST | `/api/chat` | required | `api/index.py:1150` | Gemini |
| GET | `/api/documents/{doc_id}/chat` | required | `api/index.py:1184` | Firestore |
| PUT | `/api/documents/{doc_id}/chat` | required | `api/index.py:1198` | Firestore |
| GET | `/api/documents/{doc_id}/quiz/attempts` | required | `api/index.py:1215` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/attempts` | required | `api/index.py:1220` | Firestore |
| POST | `/api/documents/{doc_id}/quiz/regenerate` | required | `api/index.py:1231` | Gemini, Firestore |
| POST | `/api/documents/{doc_id}/summary/regenerate` | required | `api/index.py:1293` | Gemini, Firestore |
| POST | `/api/documents/{doc_id}/podcast/regenerate` | required | `api/index.py:1328` | Gemini, Firestore |
| GET | `/api/podcast/audio-status/{doc_id}` | required | `api/index.py:1368` | Firestore |
| POST | `/api/podcast/segment-audio` | required | `api/index.py:1378` | ElevenLabs (on cache miss), Firestore |

"Required" auth means `Depends(require_user)` — see §3.1.
