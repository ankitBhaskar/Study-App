# Voice Lab

Isolated proof of concept for testing voice generation providers before integrating one into the main Study App.

This folder is intentionally separate from the existing production React and FastAPI files.

## Providers included

- Gemini speech generation
- OpenAI / ChatGPT text to speech
- ElevenLabs text to speech

## What this POC tests

- Voice quality
- API latency
- Audio file size
- Character count
- Estimated cost
- Error response visibility
- Provider switching through the same backend interface

## Local setup

Backend:

```bash
cd voice-lab/backend
python -m venv .venv
pip install -r requirements.txt
uvicorn main:app --reload --port 8010
```

Frontend:

```bash
cd voice-lab/frontend
npm install
npm run dev
```

## Environment variables

Create `voice-lab/backend/.env` from `.env.example` and add the provider keys you want to test.

## API

Health:

```http
GET /api/voice/health
```

Generate audio:

```http
POST /api/voice/generate
Content-Type: application/json

{
  "provider": "openai",
  "text": "Welcome to the Study App voice test.",
  "voice": "alloy"
}
```

Provider values:

- `gemini`
- `openai`
- `elevenlabs`

This POC is not wired into the main Study App.
