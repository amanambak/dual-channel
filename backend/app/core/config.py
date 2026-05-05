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
    openai_realtime_ws_url: str = "wss://api.openai.com/v1/realtime?intent=transcription"
    openai_transcription_model: str = "gpt-4o-transcribe"
    openai_transcription_language: str = ""
    openai_transcription_prompt: str = ""
    llm_model: str = "gpt-5.4"
    llm_summary_model: str = "gpt-5.4"
    llm_extract_model: str = "gpt-5.4"
    request_timeout_seconds: float = 60.0

    # RAG Settings
    chroma_db_path: str = "chroma_db"
    embedding_model: str = "gemini-embedding-2"
    rag_top_k: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
