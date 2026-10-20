"""Opt-in real-model checks.

Run with:
  RUN_BGE_TESTS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 pytest tests/test_bge_integration.py -q

They are skipped by default so unit tests remain fast and CPU-only.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BGE_TESTS") != "1",
    reason="set RUN_BGE_TESTS=1 to load the real BGE models",
)


def test_bge_m3_returns_normalized_1024_dim_vector():
    from app.ingestion.embedder import BGEM3Embedder

    embedder = BGEM3Embedder("BAAI/bge-m3", 1024, "mps", use_fp16=True)
    vector = embedder.embed_query("中华绒螯蟹养殖对溶解氧有什么要求？")
    assert len(vector) == 1024
    assert abs(sum(value * value for value in vector) ** 0.5 - 1.0) < 0.01


def test_bge_reranker_prefers_relevant_passage():
    from app.retrieval.rerank import BGEReranker

    path = Path("../../models/bge-reranker-v2-m3")
    if not path.exists():
        pytest.skip("local BGE reranker path is not present")
    reranker = BGEReranker(str(path), device="mps", use_fp16=True)
    ranked = reranker.rerank(
        "中华绒螯蟹对溶解氧有什么要求？",
        [
            ("irrelevant", "今天上海天气晴朗。"),
            ("relevant", "养殖水体溶解氧宜保持在 5 mg/L 以上。"),
        ],
        2,
    )
    assert ranked[0][0] == "relevant"
