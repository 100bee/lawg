from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RAGOps Copilot API"
    app_version: str = "0.1.0"
    database_url: str = "postgresql+psycopg://ragops:ragops@localhost:5432/ragops"
    frontend_origin: str = "http://localhost:3000"

    ai_provider: Literal["openai", "local"] = "local"
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-5.6-luna"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    chunk_size: int = 900
    chunk_overlap: int = 120
    retrieval_top_k: int = 5
    retrieval_candidate_k: int = 20
    hybrid_vector_weight: float = 0.72
    hybrid_keyword_weight: float = 0.28
    minimum_grounding_score: float = 0.08
    prompt_version: str = "ragops-v1"
    sample_data_dir: str = "data/incidents"
    evaluation_dataset_path: str = "data/evaluations.jsonl"

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
