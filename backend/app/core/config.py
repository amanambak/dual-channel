from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "audio-ai-backend"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000

    deepgram_api_key: str = ""
    deepgram_ws_url: str = "wss://api.deepgram.com/v1/listen"
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )
    llm_model: str = "gemini-3.1-flash-lite-preview"
    llm_summary_model: str = "gemini-3.1-flash-lite-preview"
    llm_extract_model: str = "gemini-3.1-flash-lite-preview"
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
