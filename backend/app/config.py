"""Application settings loaded from environment variables or a local .env."""

from functools import lru_cache
from typing import Literal

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
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    memory_embedding_provider: Literal["openai", "google"] = "openai"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dimensions: int = Field(default=768, ge=128, le=3072)
    memory_auto_save: bool = False
    memory_top_k: int = Field(default=5, ge=1, le=20)
    memory_similarity_threshold: float = Field(default=0.85, ge=0, le=1)
    memory_min_importance: float = Field(default=0.5, ge=0, le=1)
    memory_min_relevance: float = Field(default=0.25, ge=0, le=1)
    memory_min_confidence: float = Field(default=0.5, ge=0, le=1)
    memory_max_context_items: int = Field(default=5, ge=1, le=20)
    memory_extraction_max_attempts: int = Field(default=5, ge=1, le=20)
    memory_temporary_ttl_days: int = Field(default=30, ge=1, le=3650)
    retrieval_query_expansion_enabled: bool = True
    retrieval_max_expansions: int = Field(default=4, ge=0, le=8)
    retrieval_candidate_limit: int = Field(default=30, ge=5, le=100)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=200)
    retrieval_max_memory_tokens: int = Field(default=800, ge=100, le=8000)
    retrieval_weight_semantic: float = Field(default=0.35, ge=0, le=1)
    retrieval_weight_keyword: float = Field(default=0.15, ge=0, le=1)
    retrieval_weight_importance: float = Field(default=0.15, ge=0, le=1)
    retrieval_weight_confidence: float = Field(default=0.10, ge=0, le=1)
    retrieval_weight_recency: float = Field(default=0.10, ge=0, le=1)
    retrieval_weight_category: float = Field(default=0.10, ge=0, le=1)
    retrieval_weight_usage: float = Field(default=0.05, ge=0, le=1)
    retrieval_half_life_education_days: int = Field(default=2500, ge=1, le=36500)
    retrieval_half_life_career_days: int = Field(default=900, ge=1, le=36500)
    retrieval_half_life_preferences_days: int = Field(default=3000, ge=1, le=36500)
    retrieval_half_life_interests_days: int = Field(default=800, ge=1, le=36500)
    retrieval_half_life_projects_days: int = Field(default=180, ge=1, le=36500)
    retrieval_half_life_goals_days: int = Field(default=270, ge=1, le=36500)
    retrieval_half_life_temporary_days: int = Field(default=14, ge=1, le=36500)
    retrieval_half_life_personal_days: int = Field(default=1800, ge=1, le=36500)
    retrieval_half_life_other_days: int = Field(default=600, ge=1, le=36500)
    retrieval_min_importance: float = Field(default=0.0, ge=0, le=1)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
