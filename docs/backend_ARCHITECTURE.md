# Backend Architecture

## Purpose

The backend is the real-time processing core for the Chrome extension. It accepts the browser WebSocket session, opens one Deepgram streaming connection per active audio channel, segments turns, runs schema-driven customer-info extraction, and streams AI suggestions back to the extension.

## High-Level Flow

```mermaid
graph TD
    EXT[Chrome Extension Offscreen] -->|start_session + config| API[FastAPI WS /ws/session]
    API --> SM[SessionManager]
    SM --> SR[SessionRuntime]
    SR --> ST[session_transport]
    ST --> DG[DeepgramClient]
    DG --> DGA[Deepgram WS /v1/listen]
    DGA --> DG
    DG --> ST
    ST -->|transcript_update / utterance_end| SR
    SR -->|finalized utterance| SF[session_finalize]
    SF -->|should_extract / should_trigger| LG[LangGraph turn graph]
    LG --> EX[extract_schema]
    EX --> SN[Schema normalizer + derived fields]
    LG --> GR[generate_response]
    GR --> LC[LLMService]
    LC --> API2[LLM provider]
    API2 --> LC
    LC -->|stream chunks| GR
    GR -->|ai_response_chunk / ai_response_done| SR
    SR -->|normalized [SUMMARY]/[INFO]/[SUGGESTION]| EXT
    SR --> SUM[Session summary APIs]
```

## Main Components

### 1. API Layer

- `backend/app/api/websocket.py`

Exposes:

- `WS /ws/session`
- `GET /api/sessions/{session_id}/summary`
- `POST /api/summary`

The websocket endpoint creates a `SessionRuntime` per browser connection. Summary endpoints read from the live session state when it is available, otherwise the ad-hoc summary endpoint uses the same extraction service on supplied text.

### 2. Session Orchestration

- `backend/app/services/session_manager.py`
- `backend/app/services/session_transport.py`
- `backend/app/services/session_finalize.py`
- `backend/app/services/session_turn_runner.py`

`SessionRuntime` owns:

- websocket lifecycle
- Deepgram channel connections
- utterance buffering and debounce
- confidence and noise filtering
- high-confidence local extraction updates
- call-stage gating
- per-session message history
- durable in-memory extracted fields

`session_transport.py` accepts the `start_session` payload from the extension, normalizes Deepgram query params, and opens one Deepgram connection per channel. The current live params include `interim_results`, `multichannel`, and `punctuate`.

### 3. Deepgram Streaming

- `backend/app/services/deepgram_client.py`

Responsibilities:

- build the Deepgram WebSocket URL
- normalize query params into string form before encoding
- authorize using the Deepgram API key
- send binary PCM audio chunks
- receive transcript payloads
- close upstream streams cleanly

The live stream uses Nova-3 in this repo. `punctuate=true` is enabled for readability, while `smart_format` stays off to keep latency predictable.

### 4. Turn Graph and LLM Layer

- `backend/app/graph/factory.py`
- `backend/app/graph/nodes.py`
- `backend/app/llm/service.py`

The current turn graph is sequential:

1. `extract_schema`
2. `generate_response`

Extraction runs first when enabled so the response stage can use same-turn fields. `generate_response` streams chunks progressively, suppresses `[SKIP]`, and emits `AIChunkEvent` and `AIDoneEvent` messages for the extension.

`LLMService` builds the prompts for:

- schema extraction
- response generation
- summary generation

### 5. Schema Registry and Normalization

- `backend/app/services/schema_registry.py`
- `backend/app/services/schema_normalizer.py`
- `backend/customer_info.json`
- `backend/home_loan_schema.csv`

The schema registry loads the field definitions and metadata. The normalizer then:

- filters unknown keys
- coerces values to the expected type
- handles aliases such as `employment_type -> profession`
- derives fields such as `is_property_identified`, `existing_emi`, `is_obligation`, and `customer_earn_cash_income`
- seeds high-confidence values from explicit utterance text before the LLM runs

This is what lets the backend keep customer-info output aligned with the schema instead of emitting arbitrary JSON.

### 6. Session State

- `backend/app/models/session.py`

Important live fields:

- `messages`
- `extracted_fields`
- `customer_last_utterance`
- `agent_last_utterance`
- `rolling_summary`
- `last_suggestion`

`extracted_fields` is the durable customer-info map for the active session. Summary endpoints read directly from it.

## Transcript Handling Logic

### Interim Transcript

- forwarded to the extension immediately
- used for live UI updates
- not treated as a finalized turn

### Final Transcript

Final transcript chunks are accepted only after confidence and noise checks pass. The backend buffers them briefly, merges fragments, and emits `utterance_end` when a turn is ready to be finalized.

### Utterance Finalization

When an utterance finalizes:

1. final transcript chunks are merged
2. incomplete trailing fragments can be held for the next turn
3. high-confidence local updates are applied
4. the utterance is stored in session history
5. schema extraction may run
6. response generation may run if the gating rules allow it

## Two-Way Conversation Logic

- Channel 0 is the customer/tab audio.
- Channel 1 is the agent/microphone audio when available.
- Deepgram diarization and channel metadata are used to keep the speaker labels stable.
- Customer turns are the primary source for schema extraction.
- Agent turns are used for conversational state, call-stage detection, and response context.

## LLM Invocation Guardrails

The backend avoids unnecessary LLM calls using:

- minimum interval between turns
- minimum confidence thresholds
- noise and filler detection
- duplicate utterance suppression
- incomplete utterance buffering
- speaker filtering
- call-stage gating

This is why the backend may skip greetings, partial fragments, or repeated low-value text.

## Output Contract To Extension

The backend emits normalized live sections for the side panel:

- `[SUMMARY]`
- `[INFO]`
- `[SUGGESTION]`

Streaming chunks are sent separately as `ai_response_chunk` events, followed by `ai_response_done` once the final formatted response is ready.

## Summary Endpoints

### Session Summary

`GET /api/sessions/{session_id}/summary`

Returns the current session customer-info map:

```json
{
  "customer_info": {
    "loan_amount": "2500000",
    "cibil_score": "780"
  }
}
```

### Ad-Hoc Summary

`POST /api/summary`

Uses the same schema extraction service on supplied conversation text when there is no active live session.

## Known Constraints

- Session state is currently in-memory only
- A backend restart clears live session memory
- Deepgram payloads can contain non-transcript events that must be skipped
- Two-way conversation quality depends on diarization and audio quality
- Punctuation improves readability but does not replace debounce or turn-finalization logic

## Recommended Next Steps

- persist session/customer state in Redis or a database
- add regression tests for schema normalization and response formatting
- log per-turn LLM token usage and skipped-call reasons
- keep the Deepgram query-param normalization close to the transport boundary
