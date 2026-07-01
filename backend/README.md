# Study App Backend

Python FastAPI backend for preparing uploaded PDFs for Gemini or another LLM.

## What it does

- Accepts a PDF upload at `POST /api/pdf/prepare`
- Extracts readable text using `pypdf`
- Cleans PDF extraction artefacts such as excess whitespace and line breaks
- Splits long document text into overlapping chunks
- Returns a Gemini-ready request payload
- Does not call Gemini directly yet, so no API key is required for this step

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
curl -X POST "http://localhost:8000/api/pdf/prepare" \
  -F "file=@sample.pdf"
```

## Response shape

The endpoint returns:

- `file_name`
- `page_count`
- `char_count`
- `word_count`
- `preview`
- `chunks`
- `gemini_payload`

The `gemini_payload` can be sent to Gemini after you add the Gemini SDK or REST call.

## Important note

This backend handles text-based PDFs. Scanned PDFs normally require OCR before text can be extracted.
