from __future__ import annotations

import threading
from typing import Protocol


class Reranker(Protocol):
    name: str

    def rerank(
        self, query: str, candidates: list[tuple[str, str]], top_k: int
    ) -> list[tuple[str, float]]: ...


class NoopReranker:
    """Keeps RRF order; explicit ablation/control, not a real reranker."""

    name = "noop"

    def rerank(
        self, query: str, candidates: list[tuple[str, str]], top_k: int
    ) -> list[tuple[str, float]]:
        return [(chunk_id, 1.0 / (i + 1)) for i, (chunk_id, _) in enumerate(candidates[:top_k])]


class BGEReranker:
    """Adapter for BAAI/bge-reranker-v2-m3 (requires FlagEmbedding)."""

    name = "BAAI/bge-reranker-v2-m3"

    def __init__(
        self,
        model_name_or_path: str = "BAAI/bge-reranker-v2-m3",
        *,
        name: str | None = None,
        device: str | None = None,
        use_fp16: bool = False,
    ) -> None:
        from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]

        from app.ingestion.embedder import resolve_device

        self.model_name_or_path = model_name_or_path
        self.name = name or "BAAI/bge-reranker-v2-m3"
        self.device = resolve_device(device)
        self._lock = threading.Lock()
        self._model = FlagReranker(
            model_name_or_path,
            use_fp16=use_fp16,
            device=self.device,
        )

    def rerank(
        self, query: str, candidates: list[tuple[str, str]], top_k: int
    ) -> list[tuple[str, float]]:
        if not candidates:
            return []
        pairs = [[query, text] for _, text in candidates]
        with self._lock:
            scores = self._model.compute_score(pairs, normalize=True)
        if isinstance(scores, float):
            scores = [scores]
        ranked = sorted(zip(candidates, scores), key=lambda item: -float(item[1]))
        return [(chunk_id, float(score)) for (chunk_id, _), score in ranked[:top_k]]


def build_reranker(
    name: str | None = None,
    *,
    path: str | None = None,
    device: str | None = None,
    use_fp16: bool = False,
) -> Reranker:
    value = (name or "noop").strip()
    if value.lower() in {"", "none", "noop"}:
        return NoopReranker()
    if value.lower() in {"bge", "bge-reranker-v2-m3", "baai/bge-reranker-v2-m3"}:
        return BGEReranker(path or value, name=value, device=device, use_fp16=use_fp16)
    if "/" in value or value.startswith("."):
        return BGEReranker(value, name=value, device=device, use_fp16=use_fp16)
    raise ValueError(f"unsupported reranker: {name}")
