// Copy this to config.js before loading the extension.

const CONFIG = {
  BACKEND_WS_URL: 'ws://127.0.0.1:8000/ws/session',
  BACKEND_HTTP_URL: 'http://127.0.0.1:8000',

  DEEPGRAM_PARAMS: {
    model: 'nova-3',
    language: 'multi',
    punctuate: true,
    utterance_end_ms: 1800,
    endpointing: 400,
    encoding: 'linear16',
    sample_rate: 16000
  },

  GEMINI_MODEL: 'gemini-3.1-flash-lite-preview',
};
