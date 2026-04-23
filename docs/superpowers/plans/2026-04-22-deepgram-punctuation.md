# Deepgram Punctuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable low-latency punctuation on the live Deepgram Nova-3 transcription stream without turning on heavier smart formatting.

**Architecture:** Add `punctuate=true` to the Deepgram listen parameters at the extension config layer so the browser-side capture path sends it through the existing `start_session` payload. Add the same default on the backend session transport so the live WebSocket connection still gets punctuation if another client omits it. Keep `smart_format` disabled to avoid extra formatting latency.

**Tech Stack:** Chrome extension JavaScript, FastAPI backend, Deepgram WebSocket listen API

---

### Task 1: Enable punctuation in the extension config

**Files:**
- Modify: `extension/config.template.js`
- Modify: `extension/config.js`

- [ ] **Step 1: Update the live Deepgram params**

```js
DEEPGRAM_PARAMS: {
  model: 'nova-3',
  language: 'multi',
  punctuate: true,
  utterance_end_ms: 1800,
  endpointing: 400,
  encoding: 'linear16',
  sample_rate: 16000
}
```

- [ ] **Step 2: Verify the extension config still loads**

Run: `node -e "const cfg = require('./extension/config.js'); console.log(cfg.DEEPGRAM_PARAMS.punctuate)"`
Expected: `true`

### Task 2: Add a backend fallback for punctuation

**Files:**
- Modify: `backend/app/services/session_transport.py`

- [ ] **Step 1: Set the default punctuation flag before Deepgram connects**

```python
params.setdefault("interim_results", "true")
params.setdefault("multichannel", "true")
params.setdefault("punctuate", "true")
```

- [ ] **Step 2: Verify the backend module still compiles**

Run: `cd backend && uv run python -m compileall app`
Expected: Exit code `0` with no syntax errors

### Task 3: Sanity-check the live param path

**Files:**
- Modify: none

- [ ] **Step 1: Confirm the browser payload now includes punctuation**

Run the app, start capture, and inspect the `start_session` payload in the browser devtools network logs or console.
Expected: `deepgramParams.punctuate === true`

- [ ] **Step 2: Confirm the backend forwards punctuation to Deepgram**

Run the app and inspect backend logs for the session start path, then verify the Deepgram WebSocket URL includes `punctuate=true`.
Expected: live Deepgram connection URL contains `punctuate=true`

