#!/usr/bin/env python3
"""Refusal test: 30 questions that must not be answered from this knowledge base.

The gate under test is the production retrieval gate (hybrid + rerank): a case
passes only when the system reports ``sufficient=False`` and therefore never
calls the generator.  This is a deterministic, model-only test; it does not ask
the LLM whether it *would* have refused, so it cannot catch a gate that passes
irrelevant evidence.

Output: eval/runs/refusal_30_v1/{details.jsonl,summary.csv,manifest.json}
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings
from app.db import SessionLocal, engine
from app.ingestion.embedder import get_embedder
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.rerank import build_reranker
from app.retrieval.service import retrieve


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "refusal_30_v1.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "runs" / "refusal_30_v1")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    cases = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line]
    embedder = get_embedder(
        settings.embedding_model,
        settings.qdrant_vector_size,
        settings.embedding_device,
        settings.embedding_use_fp16,
        settings.embedding_batch_size,
        settings.embedding_max_length,
    )
    bm25 = BM25SparseEncoder(k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len)
    reranker = build_reranker(
        settings.reranker_model,
        path=settings.reranker_path,
        device=settings.reranker_device,
        use_fp16=settings.reranker_use_fp16,
    )
    details: list[dict] = []
    async with SessionLocal() as db:
        for case in cases:
            result = await retrieve(
                db,
                case["question"],
                embedder,
                bm25,
                reranker=reranker,
                top_k=args.top_k,
                mode="hybrid_rerank",
            )
            record = {
                "id": case["id"],
                "question": case["question"],
                "category": case["category"],
                "rationale": case["rationale"],
                "refused": not result.sufficient,
                "gate_reason": result.gate.get("reason"),
                "sources": len(result.evidence),
                "top_titles": [item.title for item in result.evidence[:3]],
                "top_score": round(max((item.score for item in result.evidence), default=0.0), 4),
                "retrieval_ms": result.timings.get("retrieval_ms", 0.0),
            }
            details.append(record)
            print(
                f"{record['id']} refused={record['refused']} reason={record['gate_reason']} "
                f"top={record['top_score']}",
                flush=True,
            )

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "details.jsonl").open("w", encoding="utf-8") as fh:
        for item in details:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    rows = []
    for category in sorted({item["category"] for item in details}):
        subset = [item for item in details if item["category"] == category]
        rows.append(
            {
                "category": category,
                "cases": len(subset),
                "refused": sum(item["refused"] for item in subset),
                "refusal_rate": round(sum(item["refused"] for item in subset) / len(subset), 4),
                "avg_top_score": round(statistics.mean(item["top_score"] for item in subset), 4),
            }
        )
    total = {
        "category": "ALL",
        "cases": len(details),
        "refused": sum(item["refused"] for item in details),
        "refusal_rate": round(sum(item["refused"] for item in details) / len(details), 4),
        "avg_top_score": round(statistics.mean(item["top_score"] for item in details), 4),
    }
    rows.append(total)
    with (args.out / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    dataset = args.dataset.resolve()
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset.relative_to(ROOT)),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "cases": len(details),
        "mode": "hybrid_rerank",
        "top_k": args.top_k,
        "collection": settings.qdrant_collection,
        "gate": "retrieval sufficiency gate; generation is not called when sufficient=False",
        "note": "Only the gate is tested. Cases where the gate passes are listed as failures "
        "for manual inspection, not as proven hallucinations.",
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    await engine.dispose()
    return 0 if total["refusal_rate"] >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))