# Study App

A React/Vite study MVP that turns an uploaded document into a study workflow. The project includes a Python FastAPI backend that extracts PDF text and prepares a Gemini-ready payload.

## Current features

- Responsive document upload screen with drag-and-drop interaction
- Real PDF upload → Gemini analysis producing summary, quiz and podcast script
- Interactive quiz with scoring and weak-topic feedback
- Podcast player with generated transcript
- Tutor chat answering questions scoped to the uploaded PDF via Gemini
- "Try it with a sample document" demo mode that works without a backend or API key
- Python FastAPI backend for PDF extraction, chunking and Gemini calls
- Gemini response contract for summary, Q&A, quiz validation, podcast script and PDF-scoped chat configuration

## Project structure

```text
Study-App/
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── gemini_response_contract.json
│   └── README.md
├── src/
│   ├── App.jsx
│   └── main.jsx
├── index.html
├── package.json
└── README.md
```

## Run frontend locally

```bash
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`.

## Configure the Gemini API key

The backend needs a Gemini API key to generate study content. Get one at
<https://aistudio.google.com/apikey>, then either export it:

```bash
export GEMINI_API_KEY="your-key-here"
```

or copy `backend/.env.example` to `backend/.env` and fill it in. The default
model is `gemini-2.5-flash`; override it with the `GEMINI_MODEL` environment
variable if needed.

Without a key the app still starts — uploads return a clear "key not
configured" error, and the sample-document demo mode keeps working.

## Run backend locally

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

Backend runs on `http://localhost:8000`.

## API endpoints

- `POST /api/pdf/analyze` — upload a PDF, get Gemini-generated study content (title, summary, quiz, podcast script) plus a `document_id` for chat. Requires `GEMINI_API_KEY`.
- `POST /api/chat` — ask the tutor a question scoped to an uploaded document (`{document_id, question, history}`). Requires `GEMINI_API_KEY`.
- `POST /api/pdf/prepare` — extract, clean and chunk PDF text and return a Gemini-ready payload without calling Gemini. No key needed.
- `GET /health` — reports service status and whether a Gemini key is configured.

Example:

```bash
curl -X POST "http://localhost:8000/api/pdf/analyze" -F "file=@sample.pdf"
```

## Gemini contract

The expected Gemini output shape is documented in `backend/gemini_response_contract.json`. It covers summary, Q&A, quiz validation, podcast script and chat configuration fields.

The frontend can use the Q&A and quiz fields to validate submitted answers and show feedback to the user.

## Build frontend

```bash
npm run build
```

## Notes

- The frontend calls the backend at `http://localhost:8000` by default; set `VITE_API_URL` to point elsewhere.
- Uploaded documents are held in backend memory for tutor chat, so chat context is lost when the backend restarts.
- Scanned (image-only) PDFs need OCR first; the backend returns a clear error for them.
