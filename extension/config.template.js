// Copy this to config.js before loading the extension.

const CONFIG = {
  BACKEND_WS_URL: 'ws://127.0.0.1:8000/ws/session',
  BACKEND_HTTP_URL: 'http://127.0.0.1:8000',

  SARVAM_PARAMS: {
    model: 'saaras:v3',
    mode: 'translit',
    language_code: 'hi-IN',
    sample_rate: 16000,
    input_audio_codec: 'pcm_s16le',
    encoding: 'audio/wav',
    high_vad_sensitivity: true,
    vad_signals: true
  },

  LLM_MODEL: 'gpt-5.4'
};
