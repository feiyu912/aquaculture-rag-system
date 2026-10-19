"""Run retrieval-module ablations directly against the service (no API needed).

Contextual Retrieval is intentionally excluded: enabling it requires rebuilding
the index with context_text, so it must be evaluated as a separate index config.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings
from app.db import SessionLocal, engine
from app.ingestion.embedder import get_embedder
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.service import retrieve

CONFIGS = {
    "baseline": {},
    "graph": {"enable_graph_expansion": True},
    "requirements_retry": {"enable_evidence_requirements": True, "enable_targeted_retrieval": True},
    "decomposition": {"enable_query_decomposition": True},
    "full_optional": {
        "enable_graph_expansion": True,
        "enable_evidence_requirements": True,
        "enable_targeted_retrieval": True,
        "enable_query_decomposition": True,
    },
}

FLAGS = [
    "enable_graph_expansion",
    "enable_evidence_requirements",
    "enable_targeted_retrieval",
    "enable_query_decomposition",
]


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def _run_case(db, embedder, bm25, case: dict) -> dict:
    result = await retrieve(
        db,
        case["question"],
        embedder,
        bm25,
        category=case.get("category"),
        species=case.get("species"),
        mode="hybrid",
    )
    evidence = result.evidence
    hit = any(
        item.title == case["gold_title"] and item.page in case["gold_pages"] for item in evidence
    )
    mrr = 0.0
    for rank, item in enumerate(evidence, start=1):
        if item.title == case["gold_title"] and item.page in case["gold_pages"]:
            mrr = 1.0 / rank
            break
    return {
        "id": case["id"],
        "hit": hit,
        "mrr": mrr,
        "refused": not result.sufficient,
        "sources": len(evidence),
        "reason": result.gate.get("reason"),
        "targeted": bool(result.config.get("targeted_retrieval")),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "eval" / "sample_questions.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "runs" / "ablations"))
    parser.add_argument("--mode", default="hybrid")
    args = parser.parse_args()
    cases = _load(Path(args.dataset))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    embedder = get_embedder(settings.embedding_model, settings.qdrant_vector_size)
    bm25 = BM25SparseEncoder(k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len)
    rows: list[dict] = []
    async with SessionLocal() as db:
        for name, overrides in CONFIGS.items():
            for flag in FLAGS:
                setattr(settings, flag, overrides.get(flag, False))
            details = [await _run_case(db, embedder, bm25, case) for case in cases]
            answerable = [
                item for item, case in zip(details, cases) if not case.get("expect_insufficient")
            ]
            expected_refusal = [
                item for item, case in zip(details, cases) if case.get("expect_insufficient")
            ]
            rows.append(
                {
                    "config": name,
                    "cases": len(details),
                    "hit_rate": round(
                        sum(item["hit"] for item in answerable) / max(1, len(answerable)), 3
                    ),
                    "mrr": round(
                        sum(item["mrr"] for item in answerable) / max(1, len(answerable)), 3
                    ),
                    "refusal_rate": round(
                        sum(item["refused"] for item in expected_refusal)
                        / max(1, len(expected_refusal)),
                        3,
                    ),
                    "targeted_cases": sum(item["targeted"] for item in details),
                }
            )
    for flag in FLAGS:
        setattr(settings, flag, False)
    await engine.dispose()

    csv_path = out_dir / "summary.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    asyncio.run(main())
