# Backend README

## Overview

The backend is a FastAPI service that receives live audio from the extension, streams it to Deepgram, finalizes utterances, runs schema-driven extraction, and emits streaming AI suggestions back to the browser.

## Current Behavior

- Live audio enters through a browser WebSocket session
- Deepgram returns interim and final transcript events
- Deepgram listens with `model=nova-3`, `punctuate=true`, `interim_results=true`, and channel-aware audio
- Final transcript chunks are buffered briefly, merged, and filtered
- High-confidence local updates seed obvious fields like location, salary, and loan amount before the LLM runs
- Meaningful utterances trigger schema extraction and then suggestion generation in sequence
- Customer fields found in conversation are stored using exact schema variable names
- Session summary returns customer info as key-value pairs
- The side panel also has a chat-only mode that calls the backend without Deepgram or session extraction

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
- `POST /api/summary/chat`
  Generates a chat answer that recommends which extracted field(s) should be inserted into the database:
  `{"reply": "...", "customer_info": {...}}`. The prompt is built with schema context from `home_loan_schema.csv` and `customer_info.json`, and the returned `customer_info` payload is normalized for direct insertion.
- `POST /api/chat`
  Chat-only LLM reply from a normal message plus optional short history:
  `{"reply": "..."}`

## LLM Layer

- `backend/app/llm/service.py` contains the shared LLM service used by the backend.
- The current live turn graph calls extraction first and response generation second.
- The raw model output is normalized into `[SUMMARY]`, `[INFO]`, and `[SUGGESTION]` sections before it reaches the extension.

## Source Files

- `backend/app/main.py`
- `backend/app/api/websocket.py`
- `backend/app/services/session_manager.py`
- `backend/app/services/session_transport.py`
- `backend/app/services/session_finalize.py`
- `backend/app/services/session_turn_runner.py`
- `backend/app/services/session_response.py`
- `backend/app/graph/`
- `backend/app/llm/service.py`
- `backend/app/services/deepgram_client.py`
- `backend/app/services/schema_registry.py`
- `backend/app/services/schema_normalizer.py`

## Notes

- Session state is in-memory only
- Deepgram query params are normalized to strings before the WebSocket handshake
- Punctuation is enabled for readability; smart formatting remains off for lower latency
- The ad-hoc summary endpoint uses the same schema extraction service as the live session path
- The summary-to-chat endpoint uses the shared schema registry prompt so the LLM can reason over the extracted field names before recommending what should be inserted into the database, and it returns the normalized payload for insertion
- The chat endpoint uses the same shared LLM service as the live system, but it bypasses Deepgram, turn finalization, and schema extraction
