from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Aquaculture RAG"
    debug: bool = True

    database_url: str = "postgresql+asyncpg://aquaculture:aquaculture@127.0.0.1:5432/aquaculture"
    auto_create_tables: bool = True

    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "kb_chunks_dev_v1"
    qdrant_vector_size: int = 1024
    embedding_model: str = "hashing-dev-1024"

    redis_url: str = "redis://127.0.0.1:6379/0"
    arq_queue: str = "arq:queue"

    llm_provider: str = "mock"  # mock | deepseek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_price_input_per_m: float = 0.0
    deepseek_price_output_per_m: float = 0.0

    default_retrieval_mode: str = "hybrid"  # dense | bm25 | hybrid | hybrid_rerank
    reranker_model: str = "noop"  # noop | BAAI/bge-reranker-v2-m3
    dense_top_k: int = 20
    bm25_top_k: int = 20
    rrf_k: int = 60
    rerank_top_k: int = 8
    max_sources: int = 5
    evidence_min_terms: int = 2
    evidence_min_weight: float = 3.0
    evidence_min_coverage: float = 0.3

    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    bm25_avg_len: float = 300.0

    data_dir: Path = Path("../../data")
    max_upload_mb: int = 100

    parent_target_chars: int = 900
    child_target_chars: int = 350
    child_overlap_chars: int = 60

    @property
    def data_path(self) -> Path:
        return self.data_dir.expanduser().resolve()

    @property
    def documents_path(self) -> Path:
        return self.data_path / "documents"

    @property
    def samples_path(self) -> Path:
        return self.data_path / "samples"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
