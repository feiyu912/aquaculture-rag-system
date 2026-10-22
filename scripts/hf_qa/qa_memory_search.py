#!/usr/bin/env python3
"""V1a retrieval experiment over the HF QA memory (offline, hint-only).

The memory collection is queried exactly like the verified FAQ store (dense +
BM25, RRF, both channels must agree), but it lives in its own collection and its
results are labelled L0_unverified_qa / hint_only.  Nothing here touches the
answer path: no sources event, no sufficiency gate, no citation validation.

Usage: uv run python qa_memory_search.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from qdrant_client import models

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings  # noqa: E402
from app.ingestion.embedder import get_embedder  # noqa: E402
from app.retrieval.bm25 import BM25SparseEncoder  # noqa: E402
from app.retrieval.vector_store import get_client  # noqa: E402

COLLECTION = "qa_memory_hf_v1"
EVAL = ROOT / "data" / "hf_qa" / "eval" / "eval_set_v1.jsonl"
OUT = ROOT / "data" / "hf_qa" / "qa_memory" / "retrieval_report.json"


def memory_filter() -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="source_type", match=models.MatchValue(value="qa_memory"))]
    )


def search_memory(client, dense, sparse, *, top_k: int = 3, rrf_k: int | None = None) -> list[dict]:
    k = rrf_k or settings.rrf_k
    dense_hits = client.query_points(
        collection_name=COLLECTION, query=dense, using="dense",
        query_filter=memory_filter(), limit=top_k, with_payload=True,
    ).points
    sparse_hits = client.query_points(
        collection_name=COLLECTION, query=sparse, using="bm25",
        query_filter=memory_filter(), limit=top_k, with_payload=True,
    ).points
    fused: dict[str, dict] = {}
    for rank, hit in enumerate(dense_hits, start=1):
        fused[str(hit.id)] = {"payload": dict(hit.payload or {}), "score": 1.0 / (k + rank), "dense_rank": rank, "sparse_rank": None}
    for rank, hit in enumerate(sparse_hits, start=1):
        entry = fused.setdefault(str(hit.id), {"payload": dict(hit.payload or {}), "score": 0.0, "dense_rank": None, "sparse_rank": None})
        entry["score"] += 1.0 / (k + rank)
        entry["sparse_rank"] = rank
    ordered = sorted(fused.values(), key=lambda item: -item["score"])
    return ordered


def main() -> None:
    eval_rows = [json.loads(l) for l in open(EVAL, encoding="utf-8")]
    emb = get_embedder(settings.embedding_model, settings.qdrant_vector_size, settings.embedding_device,
                       settings.embedding_use_fp16, settings.embedding_batch_size, settings.embedding_max_length)
    bm25 = BM25SparseEncoder(k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len)
    client = get_client()

    questions = [r["question"] for r in eval_rows]
    vecs = emb.embed_documents(questions)
    per_lang = defaultdict(lambda: {"n": 0, "strict_hit": 0, "any_hit": 0, "scores": []})
    examples = []
    for r, dense in zip(eval_rows, vecs):
        hits = search_memory(client, dense, bm25.query_vector(r["question"]), top_k=3)
        strict = [h for h in hits if h["dense_rank"] and h["sparse_rank"]]
        bucket = per_lang[r["language"]]
        bucket["n"] += 1
        bucket["strict_hit"] += bool(strict)
        bucket["any_hit"] += bool(hits)
        if hits:
            bucket["scores"].append(round(hits[0]["score"], 6))
        if len(examples) < 12 and hits:
            top = hits[0]["payload"]
            examples.append(
                {
                    "eval_question": r["question"],
                    "memory_question": top.get("question"),
                    "memory_answer_head": (top.get("answer") or "")[:120],
                    "evidence_level": top.get("evidence_level"),
                    "rrf_score": round(hits[0]["score"], 6),
                    "both_channels": bool(strict and strict[0]["payload"] == hits[0]["payload"]),
                }
            )

    def pct(values: list[float], p: float) -> float | None:
        if not values:
            return None
        values = sorted(values)
        return values[min(len(values) - 1, int(p * len(values)))]

    report = {
        "built_at": datetime.now(UTC).isoformat(),
        "collection": COLLECTION,
        "eval_questions": len(eval_rows),
        "policy": "dense+bm25 RRF; strict = both channels agree (same as FAQ trust policy)",
        "by_language": {
            lang: {
                "n": b["n"],
                "strict_hit_rate": round(b["strict_hit"] / b["n"], 4) if b["n"] else None,
                "any_hit_rate": round(b["any_hit"] / b["n"], 4) if b["n"] else None,
                "top1_score_p50": pct(b["scores"], 0.5),
                "top1_score_p90": pct(b["scores"], 0.9),
            }
            for lang, b in per_lang.items()
        },
        "examples": examples,
        "note": "hits are similar questions for hinting/expansion only; answers are unverified and never citable",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()