# Backend

FastAPI backend for the Chrome extension call-assist system.

## Responsibilities

- Accept live PCM audio over `WS /ws/session`
- Stream audio to Deepgram for transcription
- Aggregate transcript chunks into utterances
- Filter noise, filler, low-confidence speech, and incomplete trailing fragments
- Generate live caller suggestions through a single LangChain-based LLM service
- Extract schema-based customer fields using `home_loan_schema.csv` and `customer_info.json`
- Serve session-backed and ad-hoc customer info summaries

## Run

1. Install dependencies:
   `uv sync`
2. Configure secrets:
   `cp .env.example .env`
3. Start the server:
   `uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Endpoints

- `GET /health`
- `WS /ws/session`
- `GET /api/sessions/{session_id}/summary`
- `POST /api/summary`

## Main Modules

- [app/api/websocket.py](/home/amanpaswan/Documents/final/backend/app/api/websocket.py)
  WebSocket session entrypoint and summary APIs
- [app/services/session_manager.py](/home/amanpaswan/Documents/final/backend/app/services/session_manager.py)
  Session orchestration, transcript gating, utterance finalization, and LLM triggering
- [app/services/deepgram_client.py](/home/amanpaswan/Documents/final/backend/app/services/deepgram_client.py)
  Upstream Deepgram streaming client
- [app/llm/service.py](app/llm/service.py)
  Single LangChain-based LLM entrypoint for prompts, summaries, extraction, and streaming replies
- [app/graph/](app/graph/)
  LangGraph turn orchestration and state graph
- [app/services/session_transport.py](app/services/session_transport.py)
  WebSocket and Deepgram lifecycle helpers
- [app/services/session_text.py](app/services/session_text.py)
  Transcript normalization and call-stage heuristics
- [app/services/schema_registry.py](/home/amanpaswan/Documents/final/backend/app/services/schema_registry.py)
  Loads valid customer-info field names from the backend schema files

## Documentation

- [docs/backend_README.md](/home/amanpaswan/Documents/final/docs/backend_README.md)
- [docs/backend_ARCHITECTURE.md](/home/amanpaswan/Documents/final/docs/backend_ARCHITECTURE.md)
