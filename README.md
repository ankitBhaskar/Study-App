# Study App

A React/Vite study app that turns an uploaded PDF into a study workflow: Gemini-generated summary, quiz, podcast script and a document-scoped tutor chat. The API is a Python FastAPI app deployed as Vercel serverless functions, so the whole project runs on Vercel from this one repo.

## Current features

- Firebase email/password login — uploading, chat and podcast audio require an account, with no public sign-up form
- Optional email allowlist (`ALLOWED_EMAILS`) to restrict the app to specific accounts only
- Per-user daily usage limit on AI actions (analyze / chat / audio), enforced server-side
- Document history stored per-account in Firestore (title, summary, quiz, podcast script and the extracted text — never the PDF file itself) with reopen/delete/clear-all; Tutor chat works on reopened documents
- Responsive document upload screen with drag-and-drop interaction
- Real PDF upload → Gemini analysis producing summary, quiz and podcast script
- Interactive quiz with scoring and weak-topic feedback; generate a fresh, non-repeating set of questions on demand, and every attempt is saved so past scores and answers can be reviewed later
- Summary can be regenerated with a different length (concise/detailed) or focused on a specific topic in the document
- Podcast player with generated transcript; regenerate the script in a different style (two-host conversation, solo narrator, or interview) at any time
- AI podcast audio: two distinct ElevenLabs voices read the generated script; once generated for a document, audio is cached in Firestore and reused free on later visits instead of calling ElevenLabs again
- Chat and summary text render markdown (bold, lists, etc.) instead of showing raw asterisks
- Tutor chat answering questions scoped to the uploaded PDF via Gemini
- "Try it with a sample document" demo mode that works without signing in
- Configurable Gemini model, ElevenLabs model/voices and daily usage limit via environment variables

## Project structure

```text
Study-App/
├── api/
│   └── index.py          # FastAPI app, deployed as a Vercel Python function
├── src/
│   ├── App.jsx
│   ├── firebase.js        # Firebase client SDK init (Auth)
│   └── main.jsx
├── index.html
├── package.json
├── requirements.txt      # Python dependencies (used by Vercel and local dev)
├── vercel.json           # Routes /api/* to the Python function
├── .env.example          # Local-dev API key template
├── gemini_response_contract.json
├── API_INTEGRATIONS.md   # Every external API call: prompts, file/line, request/response shapes
└── README.md
```

## Deploy on Vercel

The repo is zero-config for Vercel: the Vite frontend is built as static assets and `api/index.py` is deployed as a Python serverless function handling all `/api/*` routes.

### 1. Create a Firebase project

1. Go to [console.firebase.google.com](https://console.firebase.google.com) → **Add project**.
2. **Build → Authentication → Get started** → enable the **Email/Password** sign-in provider.
3. **Build → Firestore Database → Create database** → pick a region close to your Vercel deployment → start in **Production mode** (the backend uses admin credentials that bypass rules, so no rules tuning is needed).
4. **Project settings → General → Your apps** → click the web (`</>`) icon → register an app → copy the `firebaseConfig` values. These are public identifiers, safe to expose in the frontend bundle.
5. **Project settings → Service accounts → Generate new private key** → downloads a JSON file. This is a secret — never commit it or expose it to the frontend.
6. Create your own account: **Authentication → Users → Add user** → enter your email and a password. There's no public sign-up screen in the app, so this is how you (and anyone else you explicitly invite) get an account.

### 2. Set environment variables in Vercel

In Vercel: your project → **Settings → Environment Variables**:

- `GEMINI_API_KEY` — from <https://aistudio.google.com/apikey>, required for study content generation
- `ELEVENLABS_API_KEY` — from <https://elevenlabs.io> (Profile → API Keys), required for podcast audio generation
- `FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY` — the three matching fields from the service account JSON downloaded above (paste `private_key` exactly as it appears, including the `\n` sequences)
- `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_STORAGE_BUCKET`, `VITE_FIREBASE_MESSAGING_SENDER_ID`, `VITE_FIREBASE_APP_ID` — from the web `firebaseConfig` object above
- `GEMINI_MODEL` — optional, defaults to `gemini-2.5-flash`
- `ELEVENLABS_MODEL` — optional, defaults to `eleven_multilingual_v2`
- `ELEVENLABS_VOICE_HOST_A` / `ELEVENLABS_VOICE_HOST_B` — optional voice IDs for the two hosts (default: Rachel and Adam)
- `DAILY_USAGE_LIMIT` — optional, defaults to `100`; caps document analyses, chat messages and audio-segment generations per user per day, combined
- `ALLOWED_EMAILS` — optional, comma-separated list (e.g. `you@example.com`). Leave unset to allow any account that exists in your Firebase project; set it to lock the app to specific emails only. Enforced server-side on every request, so it applies regardless of how a Firebase account was created.

Then **redeploy** (Deployments → ⋯ → Redeploy) — env var changes only take effect on the next deployment. Verify at `https://<your-app>.vercel.app/api/health`: `gemini_key_configured`, `elevenlabs_key_configured` and `firebase_configured` should all be `true`.

## Run locally

Frontend:

```bash
npm install
npm run dev        # http://localhost:5173
```

API (from the repo root):

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env          # then fill in your keys (see setup steps above)
uvicorn api.index:app --reload --port 8000
```

The dev frontend automatically talks to `http://localhost:8000`; set `VITE_API_URL` to point elsewhere.

### Testing locally without touching your real Firebase project

The [Firebase Local Emulator Suite](https://firebase.google.com/docs/emulator-suite) runs Auth and Firestore locally with no real credentials needed:

```bash
npx firebase-tools emulators:start --only auth,firestore --project demo-study-app
```

Then run the backend with `FIREBASE_PROJECT_ID=demo-study-app FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099` (no `FIREBASE_CLIENT_EMAIL`/`FIREBASE_PRIVATE_KEY` needed), and set `VITE_USE_FIREBASE_EMULATOR=true` for the frontend so it points at the local Auth emulator too.

## API endpoints

- `POST /api/pdf/analyze` — upload a PDF, get Gemini-generated study content (title, summary, quiz, podcast script) plus the extracted `document_context` used for tutor chat, and save the derived data to the signed-in user's Firestore history. Optional form fields choose the initial generation style: `podcast_style` (`conversation` default / `solo` / `interview`), `summary_length` (`concise` default / `detailed`), `summary_focus` (free text, optional). Requires sign-in and `GEMINI_API_KEY`; counts against the daily usage limit.
- `POST /api/chat` — ask the tutor a question scoped to the uploaded document (`{document_context, file_name, question, history}`). Requires sign-in and `GEMINI_API_KEY`; counts against the daily usage limit.
- `GET`/`PUT /api/documents/{id}/chat` — read or save the tutor chat transcript for a document, so it's restored on the next visit. Storage only, no usage-limit cost.
- `GET /api/documents/{id}/quiz/attempts` / `POST /api/documents/{id}/quiz/attempts` — list past quiz attempts (score, questions, answers; newest first, capped at 20) or record a new one. Score is computed server-side. Storage only, no usage-limit cost.
- `POST /api/documents/{id}/quiz/regenerate` — generate a new set of quiz questions from the document's saved text, explicitly avoiding the current quiz and recent attempts. Overwrites the document's stored quiz. Requires `GEMINI_API_KEY`; counts against the daily usage limit.
- `POST /api/documents/{id}/summary/regenerate` — regenerate the summary with a chosen `{length: "concise"|"detailed", focus}`. Overwrites the document's stored summary. Requires `GEMINI_API_KEY`; counts against the daily usage limit.
- `POST /api/documents/{id}/podcast/regenerate` — regenerate the podcast script in a chosen `{style: "conversation"|"solo"|"interview"}`. Overwrites the stored script and clears any cached audio for the document (it no longer matches). Requires `GEMINI_API_KEY`; counts against the daily usage limit.
- `POST /api/podcast/segment-audio` — turn one transcript segment into speech (`{text, speaker, document_id, segment_index}`; the last two are optional but enable caching); returns MP3 audio. Requires sign-in and `ELEVENLABS_API_KEY`; counts against the daily usage limit only on a cache miss. The frontend calls this once per segment and plays them back-to-back, keeping each response well under Vercel's size limits. When `document_id`/`segment_index` are given, generated audio is stored (base64, one Firestore document per segment) and reused on future requests for that exact segment — free and instant, no new ElevenLabs call or usage-limit hit.
- `GET /api/podcast/audio-status/{id}` — which segment indices already have cached audio for a document, so the player can restore itself after a reload without regenerating.
- `GET /api/profile` — the signed-in user's email, account creation date, and today's usage vs. the daily limit.
- `GET /api/documents` — the signed-in user's document history (up to 50, newest first; metadata and study data only).
- `GET /api/documents/{id}` — one history document including its stored extracted text, used to re-enable Tutor chat when reopening.
- `DELETE /api/documents/{id}` / `DELETE /api/documents` — delete one document or clear all history, including its cached audio, chat log and quiz attempts.
- `POST /api/pdf/prepare` — extract, clean and chunk PDF text and return a Gemini-ready payload without calling Gemini. No sign-in needed.
- `GET /api/health` — reports service status and whether Gemini, ElevenLabs and Firebase are configured, plus whether `ALLOWED_EMAILS` is restricting access.

See [API_INTEGRATIONS.md](API_INTEGRATIONS.md) for exact prompts, file/line references, and request/response shapes for every endpoint above.

All endpoints except `/api/pdf/prepare` and `/api/health` require an `Authorization: Bearer <Firebase ID token>` header.

Example:

```bash
curl -X POST "https://<your-app>.vercel.app/api/pdf/analyze" \
  -H "Authorization: Bearer $ID_TOKEN" \
  -F "file=@sample.pdf"
```

## Gemini contract

The expected Gemini output shape is documented in `gemini_response_contract.json`. It covers summary, Q&A, quiz validation, podcast script and chat configuration fields.

## Notes

- Upload limit is 4 MB — Vercel serverless functions reject larger request bodies.
- Serverless functions keep no state between requests, so the browser holds the extracted document text and sends it with each tutor-chat message.
- Document history stores the derived study data plus the extracted text (truncated to fit Firestore's 1 MiB document cap) — the PDF file itself is never stored. All four tabs, including Tutor chat, work when reopening a document from history. Documents analyzed before text storage was added show a re-upload notice in the Tutor tab.
- Scanned (image-only) PDFs need OCR first; the API returns a clear error for them.
- There's no public sign-up form — new accounts are created manually in the Firebase Console (Authentication → Users). Hiding the sign-up button is UX only; the real access control is the server-side `ALLOWED_EMAILS` check, since Firebase's public API key means anyone could otherwise call Firebase's own sign-up endpoint directly.
- If a signed-in account isn't on `ALLOWED_EMAILS`, every API call returns 403 and the frontend immediately signs them out with a clear message rather than leaving them stuck in a broken logged-in state.
- Without a key configured, the corresponding feature returns a clear "not configured" error rather than failing silently; the sample-document demo mode never needs any key and works for anyone signed in.
