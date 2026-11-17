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
    openai_stt_model: str = "whisper-1"
    openai_tts_model: str = "tts-1"
    openai_tts_voice: str = "alloy"
    openai_vision_model: str = "gpt-4o-mini"
    gemini_stt_model: str = "gemini-3.5-flash-lite"
    gemini_tts_model: str = "gemini-3.8-flash-tts"
    gemini_tts_voice: str = "Kore"
    max_audio_upload_mb: int = Field(default=20, ge=1, le=100)
    max_image_upload_mb: int = Field(default=10, ge=1, le=50)
    voice_enabled: bool = True
    tts_enabled: bool = True
    image_input_enabled: bool = True
    store_raw_audio: bool = False
    store_uploaded_images: bool = False
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
    retrieval_weight_utility: float = Field(default=0.05, ge=0, le=1)
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
    adaptive_processing_enabled: bool = True
    adaptive_job_max_attempts: int = Field(default=5, ge=1, le=20)
    adaptive_preference_confidence_threshold: float = Field(default=0.6, ge=0, le=1)
    adaptive_preference_evidence_threshold: int = Field(default=3, ge=2, le=20)
    adaptive_pattern_evidence_threshold: int = Field(default=2, ge=2, le=20)
    adaptive_outdated_utility_threshold: float = Field(default=0.2, ge=0, le=1)
    adaptive_outdated_age_multiplier: float = Field(default=2.0, ge=1, le=10)
    adaptive_max_preferences_in_context: int = Field(default=3, ge=1, le=10)
    adaptive_max_pattern_messages: int = Field(default=120, ge=10, le=1000)
    adaptive_feedback_context_window_minutes: int = Field(default=30, ge=1, le=1440)
    adaptive_job_interval_seconds: int = Field(default=60, ge=10, le=3600)
    knowledge_graph_enabled: bool = True
    graph_max_depth: int = Field(default=3, ge=1, le=5)
    graph_default_depth: int = Field(default=2, ge=1, le=5)
    graph_max_nodes: int = Field(default=150, ge=10, le=500)
    graph_max_edges: int = Field(default=300, ge=10, le=1000)
    graph_context_max_facts: int = Field(default=8, ge=1, le=20)
    graph_context_max_tokens: int = Field(default=400, ge=100, le=2000)
    graph_min_confidence: float = Field(default=0.3, ge=0, le=1)
    graph_max_aliases: int = Field(default=12, ge=1, le=50)
    graph_job_max_attempts: int = Field(default=5, ge=1, le=20)
    graph_job_interval_seconds: int = Field(default=60, ge=10, le=3600)
    graph_max_rebuild_memories: int = Field(default=500, ge=10, le=5000)
    graph_auto_activate_on_approval: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
