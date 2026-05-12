# Backend

FastAPI backend for the Chrome extension call-assist system.

## Responsibilities

- Accept live PCM audio over `WS /ws/session`
- Stream audio to OpenAI Realtime for transcription
- Aggregate transcript chunks into utterances
- Filter noise, filler, low-confidence speech, and incomplete trailing fragments
- Generate live caller suggestions through a single LangChain-based LLM service
- Extract customer fields using the registry built from `FIELD_MAPPING_CORE.json`
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

## Main Modules

- [app/api/websocket.py](/home/amanpaswan/Documents/final/backend/app/api/websocket.py)
  WebSocket session entrypoint and summary APIs
- [app/services/session_manager.py](/home/amanpaswan/Documents/final/backend/app/services/session_manager.py)
  Session orchestration, transcript gating, utterance finalization, and LLM triggering
- [app/services/openai_realtime_client.py](app/services/openai_realtime_client.py)
  Upstream OpenAI Realtime transcription client
- [app/llm/service.py](app/llm/service.py)
  Single LangChain-based LLM entrypoint for prompts, summaries, extraction, and streaming replies
- [app/graph/](app/graph/)
  LangGraph turn orchestration and state graph
- [app/services/session_transport.py](app/services/session_transport.py)
  WebSocket and transcription lifecycle helpers
- [app/services/session_text.py](app/services/session_text.py)
  Transcript normalization and call-stage heuristics
- [app/services/field_registry.py](app/services/field_registry.py)
  Loads canonical field names, aliases, and database paths from `FIELD_MAPPING_CORE.json`

## Documentation

- [docs/backend_README.md](/home/amanpaswan/Documents/final/docs/backend_README.md)
- [docs/backend_ARCHITECTURE.md](/home/amanpaswan/Documents/final/docs/backend_ARCHITECTURE.md)
