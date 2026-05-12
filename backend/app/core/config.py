from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "audio-ai-backend"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000

    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )
    openai_api_key: str = ""
    sarvam_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("SARVAM_API_KEY", "SARVAM_API_SUBSCRIPTION_KEY"),
    )
    sarvam_ws_url: str = "wss://api.sarvam.ai/speech-to-text/ws"
    sarvam_model: str = "saaras:v3"
    sarvam_mode: str = "translit"
    sarvam_language_code: str = "hi-IN"
    sarvam_sample_rate: int = 16000
    sarvam_input_audio_codec: str = "pcm_s16le"
    sarvam_encoding: str = "audio/wav"
    sarvam_high_vad_sensitivity: bool = True
    sarvam_vad_signals: bool = True
    sarvam_flush_signal: bool = False
    sarvam_flush_interval_ms: int = 0
    sarvam_asr_model: str = "saaras:v3"
    sarvam_asr_mode: str = "translit"
    sarvam_asr_language_code: str = "hi-IN"
    sarvam_asr_sample_rate: int = 16000
    sarvam_asr_input_audio_codec: str = "pcm_s16le"
    sarvam_asr_high_vad_sensitivity: bool = True
    sarvam_asr_flush_signal: bool = True
    sarvam_asr_flush_interval_ms: int = 500
    sarvam_asr_positive_speech_threshold: str = "0.45"
    sarvam_asr_negative_speech_threshold: str = "0.35"
    sarvam_asr_min_speech_frames: str = "1"
    sarvam_asr_first_turn_min_speech_frames: str = "1"
    sarvam_asr_negative_frames_count: str = "1"
    sarvam_asr_negative_frames_window: str = "3"
    sarvam_asr_pre_speech_pad_frames: str = "5"
    llm_model: str = "gpt-5.4"
    llm_summary_model: str = "gpt-5.4"
    llm_extract_model: str = "gpt-5.4"
    request_timeout_seconds: float = 60.0

    # RAG Settings
    chroma_db_path: str = "chroma_db"
    embedding_model: str = "gemini-embedding-2"
    rag_top_k: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
