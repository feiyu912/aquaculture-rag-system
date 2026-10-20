"""Small A/B: rule IR vs LLM planner on retrieval metrics.

Only retrieval is measured.  This script makes no claim about generated answer
quality; that requires a separate, blinded answer review.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_retrieval_metrics import gold_grades, score_ranking

from app.config import settings
from app.db import SessionLocal
from app.generation.llm import build_generator
from app.ingestion.embedder import get_embedder
from app.query.planner import planner_from_generator
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.rerank import build_reranker
from app.retrieval.service import retrieve

DEFAULT_IDS = ("R026", "R061", "R062", "R066")


def read_cases(path: Path, ids: tuple[str, ...]) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            case = json.loads(line)
            if case["id"] in ids:
                cases.append(case)
    return cases


async def run(cases: list[dict], mode: str, top_k: int, out: Path, metadata: dict) -> dict:
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
        path=settings.reranker_path or None,
        device=settings.reranker_device,
        use_fp16=settings.reranker_use_fp16,
    )
    generator = build_generator()
    metadata["planner_model"] = getattr(generator, "name", type(generator).__name__)
    planner = planner_from_generator(generator)
    details = []
    async with SessionLocal() as db:
        for case in cases:
            gold = gold_grades(case, unit="parent")
            row = {"id": case["id"], "question": case["question"], "gold": gold}
            for family in ("rules", "llm"):
                settings.enable_llm_planner = family == "llm"
                result = await retrieve(
                    db,
                    case["question"],
                    embedder,
                    bm25,
                    reranker=reranker,
                    planner=planner if family == "llm" else None,
                    top_k=top_k,
                    mode=mode,
                    category=case.get("category"),
                    species=case.get("species"),
                )
                ranked = [str(item.parent_chunk_id) for item in result.evidence]
                row[family] = {
                    "metrics": score_ranking(ranked, gold),
                    "sources": len(result.evidence),
                    "retrieval_ms": round(result.timings.get("retrieval_ms", 0.0), 1),
                    "planner": (result.config or {}).get("llm_planner"),
                    "query_ir": (result.config or {}).get("query_ir"),
                    "ranked_parent_ids": ranked,
                }
            details.append(row)
            print(
                f"{case['id']} rule recall@5={row['rules']['metrics']['recall@5']:.2f} "
                f"llm recall@5={row['llm']['metrics']['recall@5']:.2f} "
                f"used={(row['llm']['planner'] or {}).get('used_llm')} "
                f"err={(row['llm']['planner'] or {}).get('error')}",
                flush=True,
            )
    settings.enable_llm_planner = False
    summary = {
        **metadata,
        "cases": len(details),
        "mode": mode,
        "top_k": top_k,
        "metrics": {},
    }
    for family in ("rules", "llm"):
        summary["metrics"][family] = {
            key: round(statistics.mean(item[family]["metrics"][key] for item in details), 4)
            for key in ("recall@5", "recall@10", "ndcg@5", "ndcg@10", "mrr@10")
        }
    summary["llm_used"] = sum(
        1 for item in details if (item["llm"]["planner"] or {}).get("used_llm")
    )
    summary["llm_errors"] = sum(
        1 for item in details if (item["llm"]["planner"] or {}).get("error")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"summary": summary, "details": details}, ensure_ascii=False, indent=2) + "\n"
    )
    (out.parent / "planner_retrieval_ab_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=ROOT / "eval" / "real_questions_v1.jsonl")
    parser.add_argument("--ids", nargs="+", default=list(DEFAULT_IDS))
    parser.add_argument("--mode", default="hybrid_rerank")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "eval" / "runs" / "planner_retrieval_ab.json"
    )
    args = parser.parse_args()
    cases = read_cases(args.cases, tuple(args.ids))
    if not cases:
        raise SystemExit("no matching cases")
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "planner_model": None,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "planner_max_tokens": settings.planner_max_tokens,
        "planner_timeout_s": settings.planner_timeout_s,
    }
    asyncio.run(run(cases, args.mode, args.top_k, args.out, metadata))


if __name__ == "__main__":
    main()
