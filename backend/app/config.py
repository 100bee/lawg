from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Lawg API"
    app_version: str = "0.1.0"
    database_url: str = "postgresql+psycopg://ragops:ragops@localhost:5432/ragops"
    frontend_origin: str = "http://localhost:3000"

    ai_provider: Literal["openai", "gemini", "local"] = "local"
    gemini_api_key: str | None = None
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_timeout_seconds: float = Field(default=45, gt=0)
    # Free-tier models return 503 under load; retry once, then try this model for generation (never embeddings).
    gemini_fallback_chat_model: str | None = "gemini-3.1-flash-lite"
    gemini_retry_delay_seconds: float = Field(default=2, ge=0)
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-5-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    chunk_size: int = 900
    chunk_overlap: int = 120
    retrieval_top_k: int = 5
    retrieval_candidate_k: int = 20
    hybrid_vector_weight: float = 0.72
    hybrid_keyword_weight: float = 0.28
    minimum_grounding_score: float = 0.08
    minimum_semantic_score: float = Field(default=0.35, ge=0, le=1)
    # Gemini cosine scores sit near 0.54 even for off-domain questions, so 0.35 accepts everything.
    # 0.62 = midpoint of the dev-split gap (refusals <= 0.548, answerable >= 0.693); challenge is held out.
    gemini_minimum_semantic_score: float = Field(default=0.62, ge=0, le=1)
    minimum_keyword_coverage: float = Field(default=0.20, ge=0, le=1)
    minimum_keyword_matches: int = Field(default=2, ge=1)
    openai_timeout_seconds: float = Field(default=45, gt=0)
    prompt_version: str = "ragops-v2"
    sample_data_dir: str = "data/sources"
    evaluation_dataset_path: str = "data/evaluations.jsonl"

    @property
    def chat_model(self) -> str:
        if self.ai_provider == "gemini":
            return self.gemini_chat_model
        return self.openai_chat_model if self.ai_provider == "openai" else "local-template"

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
