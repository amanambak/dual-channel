# Chrome Extension Frontend

This folder contains the plain-JS Chrome extension frontend.

## Responsibilities

- Start and stop tab audio monitoring
- Capture tab audio with `tabCapture`
- Convert audio to PCM in `capture-worklet.js`
- Send PCM to the FastAPI backend over WebSocket
- Render live transcripts, AI suggestions, and conversation summaries

## Setup

1. Copy `config.template.js` to `config.js`.
2. Point `BACKEND_WS_URL` and `BACKEND_HTTP_URL` to the FastAPI backend.
3. Load this `extension/` folder as an unpacked extension in Chrome.

## Runtime Split

- `background.js`: extension orchestration, local storage, and summary routing
- `offscreen.js`: audio capture and backend WebSocket bridge
- `sidepanel.js`: live transcript and suggestion UI
- `capture-worklet.js`: Float32 to Int16 PCM conversion

## Current Config

The extension forwards `DEEPGRAM_PARAMS` to the backend as part of `start_session`.

Recommended live values:

- `model: 'nova-3'`
- `language: 'multi'`
- `punctuate: true`
- `utterance_end_ms`
- `endpointing`
- `encoding: 'linear16'`
- `sample_rate: 16000`

Do not set Deepgram or Gemini API keys in the extension. The backend owns those integrations.

## UI Contract

The side panel renders:

- live transcript cards
- backend response sections:
  - `Context`
  - `Customer Info`
  - `Suggestion`

Backend AI responses stream through `AI_RESPONSE_CHUNK` and are finalized with `AI_RESPONSE_DONE`.

## Storage

The extension stores:

- `messages`
- `isCapturing`
- `currentSessionId`
- `captureMode`

This lets the side panel restore conversation state when reopened and reuse the live session summary endpoint when available.
