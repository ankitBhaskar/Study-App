# Study App Backend

Python FastAPI backend that extracts uploaded PDF text and calls Gemini to generate study content.

## What it does

- Accepts a PDF upload at `POST /api/pdf/analyze`, extracts text with `pypdf`, sends it to Gemini and returns a title, summary points, quiz questions and a two-host podcast script
- Serves a document-scoped tutor chat at `POST /api/chat` (uses the `document_id` returned by analyze)
- Still exposes `POST /api/pdf/prepare` for extraction/chunking without calling Gemini (no key needed)
- `GET /health` reports whether a Gemini key is configured

## Configure the API key

Get a Gemini API key at <https://aistudio.google.com/apikey>, then either:

```bash
export GEMINI_API_KEY="your-key-here"
```

or copy `.env.example` to `.env` in this directory and fill it in (loaded automatically on startup).

Optional environment variables:

- `GEMINI_MODEL` — defaults to `gemini-2.5-flash`
- `GEMINI_API_BASE` — defaults to the official Generative Language API endpoint

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

On Windows PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Test the API

```bash
curl -X POST "http://localhost:8000/api/pdf/analyze" \
  -F "file=@sample.pdf"
```

## Response shape

`POST /api/pdf/analyze` returns:

- `document_id` — pass this to `/api/chat` for tutor questions
- `file_name`, `page_count`
- `title`
- `summary` — list of key-point strings
- `quiz` — list of `{q, options, answer, topic, explanation}`
- `podcast` — `{duration, hosts, transcript: [{t, who, line}]}`

`POST /api/chat` accepts `{document_id, question, history: [{role, text}]}` and returns `{answer}`.

Uploaded documents are stored in memory only; after a backend restart the frontend needs to re-upload the PDF before chatting.

## Important note

This backend handles text-based PDFs. Scanned PDFs normally require OCR before text can be extracted.
