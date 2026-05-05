// Copy this to config.js before loading the extension.

const CONFIG = {
  BACKEND_WS_URL: 'ws://127.0.0.1:8000/ws/session',
  BACKEND_HTTP_URL: 'http://127.0.0.1:8000',

  OPENAI_TRANSCRIPTION_PARAMS: {
    model: 'gpt-4o-transcribe',
    language: '',
    prompt: 'Transcribe Indian home-loan calls accurately. Expect Hindi, English, and Hinglish. Prefer Roman-script output for Hindi/Hinglish words, keep loan and banking terms literal, and do not guess words from brief noise or cross-talk.',
    vad_type: 'server_vad',
    vad_threshold: 0.6,
    prefix_padding_ms: 80,
    silence_duration_ms: 120
  },

  LLM_MODEL: 'gpt-5.4',

  // --- Magic number constants ---
  UTTERANCE_MERGE_WINDOW_MS: 1800,
  OFFSCREEN_INIT_DELAY_MS: 250,
  MAX_MESSAGES: 1000,
  MAX_CUSTOMER_HISTORY: 20,
  MAX_AGENT_HISTORY: 20,
  CONFIDENCE_THRESHOLD_EXTRACT: 0.45,
  CONFIDENCE_THRESHOLD_INVOKE: 0.45,
  CONFIDENCE_DEFAULT: 0.75,
  LLM_COOLDOWN_SECONDS: 3.0,
  DUPLICATE_TURN_WINDOW_SECONDS: 25.0,
  MAX_LEAF_ITEMS: 25,
  MAX_FIELDS_DEFAULT: 700,
};
