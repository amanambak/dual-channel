# Backend README

## Overview

The backend is a FastAPI service that receives live audio from the extension, streams it to Deepgram, turns final transcript segments into utterances, runs Gemini for caller suggestions, and maintains per-session customer info extracted against the home loan schema.

## Current Behavior

- Live audio enters through a browser WebSocket session
- Deepgram returns interim and final transcript events
- Final transcript chunks are buffered briefly, merged, and filtered
- Low-value or noisy transcript fragments are ignored
- Meaningful utterances trigger Gemini suggestion generation
- Customer fields found in conversation are stored using exact schema variable names
- Session summary returns customer info as key-value pairs

## Run

```bash
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment

- `DEEPGRAM_API_KEY`
- `DEEPGRAM_WS_URL`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `SUMMARY_MODEL`
- `HOST`
- `PORT`

## API Surface

- `GET /health`
- `WS /ws/session`
- `GET /api/sessions/{session_id}/summary`
  Returns session customer info:
  `{"customer_info": {...}}`
- `POST /api/summary`
  Ad-hoc extraction from supplied conversation text:
  `{"customer_info": {...}}`

## Source Files

- [backend/app/main.py](/home/amanpaswan/Documents/final/backend/app/main.py)
- [backend/app/api/websocket.py](/home/amanpaswan/Documents/final/backend/app/api/websocket.py)
- [backend/app/services/session_manager.py](/home/amanpaswan/Documents/final/backend/app/services/session_manager.py)
- [backend/app/services/gemini_client.py](/home/amanpaswan/Documents/final/backend/app/services/gemini_client.py)
- [backend/app/services/deepgram_client.py](/home/amanpaswan/Documents/final/backend/app/services/deepgram_client.py)
- [backend/app/services/schema_registry.py](/home/amanpaswan/Documents/final/backend/app/services/schema_registry.py)
