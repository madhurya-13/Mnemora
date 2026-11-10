"""Application settings loaded from environment variables or a local .env."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    application_name: str = "MNEMORA"
    application_version: str = "1.0.0"
    frontend_url: str = "http://localhost:3000"
    google_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_temperature: float = Field(default=0.7, ge=0, le=2)
    gemini_max_tokens: int = Field(default=2048, ge=1, le=16384)
    gemini_timeout_seconds: int = Field(default=60, ge=5, le=300)
    assistant_system_prompt: str = Field(default="", validation_alias="MNEMORA_SYSTEM_PROMPT")
    chat_max_history_messages: int = Field(default=20, ge=0, le=100)
    chat_max_message_length: int = Field(default=8000, ge=1, le=50000)
    database_url: str = "sqlite:///./memory_agent.db"
    guest_session_cookie: str = "mnemora_session"
    guest_session_max_age_seconds: int = Field(default=31536000, ge=86400, le=63072000)
    session_cookie_secure: bool = False
    redis_url: str = "redis://localhost:6379"
    chroma_db_path: str = "./chroma_db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
