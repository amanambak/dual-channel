# LangChain and LangGraph Migration Plan

> Historical note: the codebase has already been simplified into a single `backend/app/llm/service.py` entrypoint for the active LLM path. This document is kept as the original migration rationale.

## Goal

Migrate the current backend toward a graph-based LLM orchestration layer while keeping the real-time audio transport custom. The main objectives are:

- make session logic easier to reason about
- support branching call flows and durable state
- reduce provider lock-in so Gemini can be replaced with minimal code changes
- keep the WebSocket, Deepgram, and browser-extension plumbing stable

## What Should Stay Custom

Do not move these parts into LangChain/LangGraph:

- `backend/app/services/deepgram_client.py`
- `backend/app/api/websocket.py`
- audio chunk routing, WebSocket lifecycle, and extension event contracts

These are transport concerns, not LLM orchestration concerns.

## What Should Move

The current `SessionRuntime` in `backend/app/services/session_manager.py` mixes state management, filtering, extraction, summary generation, and decision logic. That should be split into graph nodes:

1. transcript normalization and noise filtering
2. utterance finalization
3. schema extraction
4. call-stage classification
5. suggestion generation
6. summary generation
7. persistence of session state

LangGraph fits this better than LangChain alone because the flow is stateful, branching, and event-driven.

## Proposed Architecture

### 1. Core Domain Layer

Create provider-agnostic domain objects:

- `ConversationState`
- `Utterance`
- `ExtractionResult`
- `SuggestionResult`
- `SummaryResult`

Keep these free of Gemini, OpenAI, Anthropic, or LangChain types.

### 2. AI Provider Interface

Create a narrow adapter interface such as:

- `generate_stream(prompt, context) -> async iterator`
- `generate_json(prompt, schema, context) -> dict`
- `generate_text(prompt, context) -> str`

Implement one adapter per provider:

- `GeminiProvider`
- `OpenAIProvider`
- `AnthropicProvider`

Route all model access through a factory selected by config, for example `AI_PROVIDER=google_genai` or `AI_PROVIDER=openai`.

### 3. LangChain Layer

Use LangChain only where it adds value:

- prompt templates
- structured output parsing
- tool wrappers
- provider adapters

Avoid spreading LangChain objects through the codebase. The app should talk to your provider interface, not directly to chain internals.

### 4. LangGraph Layer

Model the session as a graph with explicit state transitions:

- `ingest_utterance`
- `should_process`
- `extract_fields`
- `update_call_stage`
- `generate_suggestion`
- `generate_summary`
- `persist_state`

This lets you add branches such as:

- customer vs agent turns
- low-confidence utterances
- missing-field follow-up questions
- human approval before sending a suggestion

## Migration Phases

### Phase 1: Introduce Provider Abstraction

Move Gemini calls behind a provider interface without changing behavior. This is the lowest-risk step and unlocks model swapping first.

### Phase 2: Isolate Session Logic

Refactor `SessionRuntime` so decision logic is split into pure functions and service calls. Keep the runtime behavior unchanged.

### Phase 3: Add LangGraph

Move finalized utterance handling into a graph. Keep Deepgram and WebSocket code outside the graph boundary.

### Phase 4: Replace Ad-Hoc Prompting

Use LangChain prompt templates and structured output for extraction, summary, and suggestions.

### Phase 5: Add Persistence and Retries

Persist session state in Redis or a database so graphs can resume after restarts.

## Provider-Swap Rules

To keep provider changes cheap:

- never import provider SDKs outside adapter modules
- never store provider-specific response objects in session state
- keep prompt text in one place per task
- keep output parsing behind a provider-neutral result model
- prefer JSON schema or structured output for extraction paths

## Features Enabled After Migration

- durable conversation memory and replay
- explicit call-flow branching
- better observability of why an AI action happened
- human-in-the-loop checkpoints
- easier A/B testing between providers
- tool use for CRM lookup, eligibility checks, policy retrieval, or RAG
- stronger typed extraction for customer fields

## Recommended Target Shape

The final call path should look like this:

1. audio arrives from the extension
2. Deepgram produces transcript events
3. session runtime finalizes an utterance
4. LangGraph receives the utterance and current state
5. provider adapter executes the required LLM step
6. normalized results update session memory
7. the backend emits the existing extension events

## Risks

- over-abstracting too early can make the code harder to debug
- moving transport logic into LangGraph would create unnecessary complexity
- provider output differences can break parsing unless outputs are structured

## Recommendation

Do not do a full rewrite. Start with a provider abstraction, then move only the orchestration layer into LangGraph. Keep LangChain as a helper layer, not the center of the application. That gives you provider flexibility without forcing a large rewrite of the real-time audio stack.
