# Study App

A React/Vite study app that turns an uploaded PDF into a study workflow: Gemini-generated summary, quiz, podcast script and a document-scoped tutor chat. The API is a Python FastAPI app deployed as Vercel serverless functions, so the whole project runs on Vercel from this one repo.

## Current features

- Firebase email/password login — uploading, chat and podcast audio require an account
- Per-user daily usage limit on AI actions (analyze / chat / audio), enforced server-side
- Document history stored per-account in Firestore (title, summary, quiz, podcast script only — never the PDF or its extracted text) with reopen/delete/clear-all
- Responsive document upload screen with drag-and-drop interaction
- Real PDF upload → Gemini analysis producing summary, quiz and podcast script
- Interactive quiz with scoring and weak-topic feedback
- Podcast player with generated transcript
- AI podcast audio: two distinct ElevenLabs voices read the generated script
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

### 2. Set environment variables in Vercel

In Vercel: your project → **Settings → Environment Variables**:

- `GEMINI_API_KEY` — from <https://aistudio.google.com/apikey>, required for study content generation
- `ELEVENLABS_API_KEY` — from <https://elevenlabs.io> (Profile → API Keys), required for podcast audio generation
- `FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY` — the three matching fields from the service account JSON downloaded above (paste `private_key` exactly as it appears, including the `\n` sequences)
- `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_STORAGE_BUCKET`, `VITE_FIREBASE_MESSAGING_SENDER_ID`, `VITE_FIREBASE_APP_ID` — from the web `firebaseConfig` object above
- `GEMINI_MODEL` — optional, defaults to `gemini-2.5-flash`
- `ELEVENLABS_MODEL` — optional, defaults to `eleven_multilingual_v2`
- `ELEVENLABS_VOICE_HOST_A` / `ELEVENLABS_VOICE_HOST_B` — optional voice IDs for the two hosts (default: Rachel and Adam)
- `DAILY_USAGE_LIMIT` — optional, defaults to `5`; caps document analyses, chat messages and audio-segment generations per user per day, combined

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

- `POST /api/pdf/analyze` — upload a PDF, get Gemini-generated study content (title, summary, quiz, podcast script) plus the extracted `document_context` used for tutor chat, and save the derived data to the signed-in user's Firestore history. Requires sign-in and `GEMINI_API_KEY`; counts against the daily usage limit.
- `POST /api/chat` — ask the tutor a question scoped to the uploaded document (`{document_context, file_name, question, history}`). Requires sign-in and `GEMINI_API_KEY`; counts against the daily usage limit.
- `POST /api/podcast/segment-audio` — turn one transcript segment into speech (`{text, speaker}` where speaker is 0 or 1); returns MP3 audio. Requires sign-in and `ELEVENLABS_API_KEY`; counts against the daily usage limit. The frontend calls this once per segment and plays them back-to-back, keeping each response well under Vercel's size limits.
- `GET /api/profile` — the signed-in user's email, account creation date, and today's usage vs. the daily limit.
- `GET /api/documents` — the signed-in user's document history (up to 50, newest first).
- `DELETE /api/documents/{id}` / `DELETE /api/documents` — delete one document or clear all history.
- `POST /api/pdf/prepare` — extract, clean and chunk PDF text and return a Gemini-ready payload without calling Gemini. No sign-in needed.
- `GET /api/health` — reports service status and whether Gemini, ElevenLabs and Firebase are configured.

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
- Document history stores only derived data (title, summary, quiz, podcast script) — never the PDF or its extracted text. Reopening a document from history works for Summary/Quiz/Podcast, but Tutor chat needs the PDF re-uploaded since no grounding text was retained.
- Scanned (image-only) PDFs need OCR first; the API returns a clear error for them.
- Without a key configured, the corresponding feature returns a clear "not configured" error rather than failing silently; the sample-document demo mode never needs any key and works for anyone signed in.
