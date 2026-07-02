# Study App

A React/Vite study app that turns an uploaded PDF into a study workflow: Gemini-generated summary, quiz, podcast script and a document-scoped tutor chat. The API is a Python FastAPI app deployed as Vercel serverless functions, so the whole project runs on Vercel from this one repo.

## Current features

- Responsive document upload screen with drag-and-drop interaction
- Real PDF upload → Gemini analysis producing summary, quiz and podcast script
- Interactive quiz with scoring and weak-topic feedback
- Podcast player with generated transcript
- AI podcast audio: two distinct ElevenLabs voices read the generated script
- Tutor chat answering questions scoped to the uploaded PDF via Gemini
- "Try it with a sample document" demo mode that works without an API key
- Configurable Gemini model and ElevenLabs model/voices via environment variables

## Project structure

```text
Study-App/
├── api/
│   └── index.py          # FastAPI app, deployed as a Vercel Python function
├── src/
│   ├── App.jsx
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

After importing the repo into Vercel, set the environment variables:

1. Get a Gemini API key at <https://aistudio.google.com/apikey> and an ElevenLabs API key at <https://elevenlabs.io> (Profile → API Keys)
2. In Vercel: your project → **Settings → Environment Variables**
   - `GEMINI_API_KEY` — required for study content generation
   - `ELEVENLABS_API_KEY` — required for podcast audio generation
   - `GEMINI_MODEL` — optional, defaults to `gemini-2.5-flash`; change it anytime to switch models
   - `ELEVENLABS_MODEL` — optional, defaults to `eleven_multilingual_v2`
   - `ELEVENLABS_VOICE_HOST_A` / `ELEVENLABS_VOICE_HOST_B` — optional voice IDs for the two hosts (default: Rachel and Adam)
3. **Redeploy** (Deployments → ⋯ → Redeploy) — env var changes only take effect on the next deployment
4. Verify: open `https://<your-app>.vercel.app/api/health` — it should show `"gemini_key_configured": true` and `"elevenlabs_key_configured": true`

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
cp .env.example .env          # then paste your GEMINI_API_KEY into .env
uvicorn api.index:app --reload --port 8000
```

The dev frontend automatically talks to `http://localhost:8000`; set `VITE_API_URL` to point elsewhere.

## API endpoints

- `POST /api/pdf/analyze` — upload a PDF, get Gemini-generated study content (title, summary, quiz, podcast script) plus the extracted `document_context` used for tutor chat. Requires `GEMINI_API_KEY`.
- `POST /api/chat` — ask the tutor a question scoped to the uploaded document (`{document_context, file_name, question, history}`). Requires `GEMINI_API_KEY`.
- `POST /api/podcast/segment-audio` — turn one transcript segment into speech (`{text, speaker}` where speaker is 0 or 1); returns MP3 audio. Requires `ELEVENLABS_API_KEY`. The frontend calls this once per segment and plays them back-to-back, keeping each response well under Vercel's size limits.
- `POST /api/pdf/prepare` — extract, clean and chunk PDF text and return a Gemini-ready payload without calling Gemini. No key needed.
- `GET /api/health` — reports service status, the active Gemini model and whether a key is configured.

Example:

```bash
curl -X POST "https://<your-app>.vercel.app/api/pdf/analyze" -F "file=@sample.pdf"
```

## Gemini contract

The expected Gemini output shape is documented in `gemini_response_contract.json`. It covers summary, Q&A, quiz validation, podcast script and chat configuration fields.

## Notes

- Upload limit is 4 MB — Vercel serverless functions reject larger request bodies.
- Serverless functions keep no state between requests, so the browser holds the extracted document text and sends it with each tutor-chat message.
- Scanned (image-only) PDFs need OCR first; the API returns a clear error for them.
- Without an API key the app still deploys — uploads return a clear "key not configured" error and the sample-document demo mode keeps working.
