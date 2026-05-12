// Copy this to config.js before loading the extension.

const CONFIG = {
  BACKEND_WS_URL: 'ws://127.0.0.1:8000/ws/session',
  BACKEND_HTTP_URL: 'http://127.0.0.1:8000',

  OPENAI_TRANSCRIPTION_PARAMS: {
    model: 'gpt-4o-transcribe',
    language: '',
    prompt: 'Transcribe only the words clearly spoken in the audio. Expect Hindi, English, and Hinglish. For Hindi or Hinglish speech, use natural Roman-script Hinglish. Do not translate, paraphrase, correct, infer names, complete sentences, or add words that were not spoken. If audio is unclear or there is cross-talk, omit unclear words.',
    agentPrompt: 'Transcribe only the words clearly spoken in the audio. For Hindi or Hinglish speech, use natural Roman-script Hinglish. Do not translate, paraphrase, correct, infer names, complete sentences, or add words that were not spoken. If audio is unclear, omit unclear words.',
    vad_type: 'server_vad',
    vad_threshold: 0.45,
    prefix_padding_ms: 800,
    silence_duration_ms: 700,
    noise_reduction: 'none'
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
