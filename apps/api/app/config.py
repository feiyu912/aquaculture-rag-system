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
    qdrant_collection: str = "kb_chunks_bge_m3_v1"
    qdrant_vector_size: int = 1024
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "auto"  # auto | mps | cuda | cpu
    mps_lock_enabled: bool = True
    mps_lock_path: str = "/tmp/aquaculture_rag_mps.lock"
    embedding_use_fp16: bool = False
    embedding_batch_size: int = 8
    embedding_max_length: int = 1024
    index_manifest_required: bool = False

    redis_url: str = "redis://127.0.0.1:6379/0"
    arq_queue: str = "arq:queue"

    llm_provider: str = "mock"  # mock | deepseek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    # Generic OpenAI-compatible endpoint (SiliconFlow, vLLM, OpenAI, etc.)
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    deepseek_price_input_per_m: float = 0.0
    deepseek_price_output_per_m: float = 0.0
    # Optional pricing for a generic OpenAI-compatible endpoint.  Leave zero
    # when the gateway does not expose per-token prices; never invent one.
    openai_price_input_per_m: float = 0.0
    openai_price_output_per_m: float = 0.0

    default_retrieval_mode: str = "hybrid"  # dense | bm25 | hybrid | hybrid_rerank
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # noop | BAAI/bge-reranker-v2-m3
    reranker_path: str = ""  # optional local model dir for offline deployment
    reranker_device: str = "auto"
    reranker_use_fp16: bool = False
    dense_top_k: int = 20
    bm25_top_k: int = 20
    rrf_k: int = 60
    rerank_top_k: int = 8
    max_sources: int = 5
    evidence_min_terms: int = 2
    evidence_min_weight: float = 3.0
    evidence_min_coverage: float = 0.3

    # Incremental enhancements. Defaults keep the baseline reproducible; turn
    # them on explicitly for ablation experiments.
    enable_query_ir: bool = True
    enable_llm_planner: bool = False
    planner_max_tokens: int = 2000
    planner_timeout_s: float = 90.0
    planner_temperature: float = 0.0
    enable_claim_verification: bool = True
    enable_semantic_claims: bool = False
    semantic_claim_threshold: float = 0.65
    enable_contextual_retrieval: bool = False
    enable_evidence_requirements: bool = False
    enable_targeted_retrieval: bool = False
    enable_graph_expansion: bool = False
    graph_top_k: int = 10
    graph_rrf_weight: float = 0.7
    graph_max_hops: int = 2
    graph_max_related: int = 12
    graph_bidirectional: bool = True
    enable_query_decomposition: bool = False
    max_query_variants: int = 6
    enable_adaptive_routing: bool = False
    max_targeted_retrieval: int = 1
    # Soft-deleted documents keep their DB rows, PDFs and vectors for this many
    # days so a mistaken delete can be undone without re-ingesting.
    soft_delete_retention_days: int = 7
    # ARQ worker concurrency.  Forced to 1 when MPS is the active device: two
    # jobs in one worker would each own a model copy on the same Metal device.
    worker_max_jobs: int = 4
    # Per-source evidence reservation for questions that explicitly cite two or
    # more standards (e.g. "DB36 和 DB46 ...").  Deterministic, no gold lookup.
    enable_source_aware_retrieval: bool = True
    source_anchor_max: int = 3
    source_anchor_slots: int = 2
    source_anchor_top_k: int = 40
    source_anchor_rerank_limit: int = 8

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
