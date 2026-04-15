from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "audio-ai-backend"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000

    deepgram_api_key: str = Field(default="")
    deepgram_ws_url: str = "wss://api.deepgram.com/v1/listen"
    gemini_api_key: str = Field(default="")
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/models"

    summary_model: str = "gemini-2.5-flash"
    request_timeout_seconds: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
