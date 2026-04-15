# FastAPI Backend

This backend receives live audio from the Chrome extension over WebSocket, streams it to Deepgram for transcription, sends finalized utterances to Gemini, and exposes a summary endpoint for the extension side panel.

## Run

1. Install dependencies with `uv sync`.
3. Copy `.env.example` to `.env` and fill in API keys.
4. Start the server:
   `uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Endpoints

- `GET /health`
- `WS /ws/session`
- `GET /api/sessions/{session_id}/summary`
