# Backend README

## Overview

The backend is a FastAPI service that receives live audio from the extension, streams it to Deepgram, turns final transcript segments into utterances, runs LangChain-based LLM suggestions, and maintains per-session customer info extracted against the home loan schema.

## Current Behavior

- Live audio enters through a browser WebSocket session
- Deepgram returns interim and final transcript events
- Final transcript chunks are buffered briefly, merged, and filtered
- Low-value or noisy transcript fragments are ignored
- Meaningful utterances trigger LLM suggestion generation
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
- `LLM_API_KEY` or legacy `GEMINI_API_KEY` / `GOOGLE_API_KEY`
- `LLM_MODEL`
- `LLM_SUMMARY_MODEL`
- `LLM_EXTRACT_MODEL`
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

## LLM Layer

- `backend/app/llm/service.py` contains the single LangChain-based LLM service used by the backend.
- Use model strings like `gemini-3.1-flash-lite-preview` or `openai:gpt-4o-mini` to switch providers without code changes.

## Source Files

- [backend/app/main.py](/home/amanpaswan/Documents/final/backend/app/main.py)
- [backend/app/api/websocket.py](/home/amanpaswan/Documents/final/backend/app/api/websocket.py)
- [backend/app/services/session_manager.py](/home/amanpaswan/Documents/final/backend/app/services/session_manager.py)
- [backend/app/services/session_transport.py](/home/amanpaswan/Documents/final/backend/app/services/session_transport.py)
- [backend/app/services/session_text.py](/home/amanpaswan/Documents/final/backend/app/services/session_text.py)
- [backend/app/services/session_turn_runner.py](/home/amanpaswan/Documents/final/backend/app/services/session_turn_runner.py)
- [backend/app/services/session_response.py](/home/amanpaswan/Documents/final/backend/app/services/session_response.py)
- [backend/app/graph/](file:///home/amanpaswan/Desktop/dual-channel/backend/app/graph/)
- [backend/app/llm/service.py](file:///home/amanpaswan/Desktop/dual-channel/backend/app/llm/service.py)
- [backend/app/services/deepgram_client.py](/home/amanpaswan/Documents/final/backend/app/services/deepgram_client.py)
- [backend/app/services/schema_registry.py](/home/amanpaswan/Documents/final/backend/app/services/schema_registry.py)
