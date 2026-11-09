"""Application settings loaded from environment variables or a local .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    application_name: str = "MNEMORA"
    application_version: str = "1.0.0"
    frontend_url: str = "http://localhost:3000"
    openai_api_key: str = ""
    database_url: str = "sqlite:///./memory_agent.db"
    redis_url: str = "redis://localhost:6379"
    chroma_db_path: str = "./chroma_db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
