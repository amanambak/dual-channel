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

  LLM_MODEL: 'gpt-5.4'
};
