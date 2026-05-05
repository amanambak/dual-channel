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

  LLM_MODEL: 'gpt-5.4'
};
