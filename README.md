# Study App

A React/Vite study MVP that turns an uploaded document into a study workflow. The project includes a Python FastAPI backend that extracts PDF text and prepares a Gemini-ready payload.

## Current features

- Responsive document upload screen with drag-and-drop interaction
- Generated study summary view
- Interactive quiz with scoring and weak-topic feedback
- Simulated 10-minute podcast player and transcript
- Tutor-style chat interface with mock AI response
- Python PDF processing backend
- Gemini-ready payload generation from extracted PDF text
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

## PDF preparation endpoint

`POST /api/pdf/prepare`

Example:

```bash
curl -X POST "http://localhost:8000/api/pdf/prepare" -F "file=@sample.pdf"
```

The backend returns extracted text metadata, document chunks and a Gemini-ready payload.

## Gemini contract

The expected Gemini output shape is documented in `backend/gemini_response_contract.json`. It covers summary, Q&A, quiz validation, podcast script and chat configuration fields.

The frontend can use the Q&A and quiz fields to validate submitted answers and show feedback to the user.

## Build frontend

```bash
npm run build
```

## Notes

The frontend still uses mock generated study content. The backend prepares uploaded PDF text for Gemini, but it does not call Gemini directly yet.
