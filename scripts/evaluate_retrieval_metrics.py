#!/usr/bin/env python3
"""Chunk-level retrieval evaluation for the real question set.

This script does not call the generation model.  It measures whether the gold
child chunks (and their document/page provenance) are retrieved by each mode:

  dense, bm25, hybrid, hybrid_rerank

Gold labels are read from ``eval/real_questions_v1.jsonl``.  Every answerable
case must have at least one gold chunk; refusal cases are scored separately and
never silently treated as retrieval hits.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings
from app.db import SessionLocal, engine
from app.ingestion.embedder import get_embedder
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.rerank import build_reranker
from app.retrieval.service import retrieve

MODES = ("dense", "bm25", "hybrid", "hybrid_rerank")


def read_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            cases.append(json.loads(line))
    return cases


def gold_grades(case: dict, unit: str = "parent") -> dict[str, int]:
    grades: dict[str, int] = {}
    for item in case.get("gold") or []:
        key = (
            str(item.get("parent_chunk_id") or item["chunk_id"])
            if unit == "parent"
            else str(item["chunk_id"])
        )
        grades[key] = max(grades.get(key, 0), int(item.get("grade", 2)))
    return grades


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dcg(grades: list[int], k: int) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades[:k]))


def score_ranking(
    ranked: list[str], gold: dict[str, int], ks: tuple[int, ...] = (5, 10)
) -> dict[str, Any]:
    relevant = set(gold)
    first = next(
        (index for index, chunk_id in enumerate(ranked, start=1) if chunk_id in relevant),
        None,
    )
    result: dict[str, Any] = {
        "first_relevant_rank": first,
        "mrr@10": round(1.0 / first, 4) if first and first <= 10 else 0.0,
        "gold_rank": {
            chunk_id: next(
                (i for i, value in enumerate(ranked, start=1) if value == chunk_id),
                None,
            )
            for chunk_id in relevant
        },
    }
    for k in ks:
        retrieved = set(ranked[:k])
        result[f"recall@{k}"] = (
            round(len(retrieved & relevant) / len(relevant), 4) if relevant else 0.0
        )
        ideal = sorted(gold.values(), reverse=True)
        dcg = _dcg([gold[chunk_id] for chunk_id in ranked[:k] if chunk_id in gold], k)
        idcg = _dcg(ideal, k)
        result[f"ndcg@{k}"] = round(dcg / idcg, 4) if idcg else 0.0
    return result


def summarize(details: list[dict]) -> list[dict]:
    rows = []
    for mode in MODES:
        subset = [item for item in details if item["mode"] == mode]
        answerable = [item for item in subset if not item["expect_insufficient"]]
        insufficient = [item for item in subset if item["expect_insufficient"]]
        if not answerable:
            continue
        row = {
            "mode": mode,
            "cases": len(subset),
            "answerable": len(answerable),
            "refused": sum(item["refused"] for item in answerable),
            "insufficient_expected": len(insufficient),
            "insufficient_pass": sum(item["refused"] for item in insufficient),
            "avg_sources": round(statistics.mean(item["sources"] for item in answerable), 3),
            "avg_retrieval_ms": round(
                statistics.mean(item["retrieval_ms"] for item in answerable), 1
            ),
        }
        for metric in ("recall@5", "recall@10", "ndcg@5", "ndcg@10", "mrr@10"):
            row[metric] = round(statistics.mean(item[metric] for item in answerable), 4)
        for metric in (
            "child_recall@5",
            "child_recall@10",
            "child_ndcg@10",
            "child_mrr@10",
        ):
            row[metric] = round(statistics.mean(item[metric] for item in answerable), 4)
        rows.append(row)
    return rows


def git_dirty() -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())
    except Exception:
        return True


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


async def run(
    dataset: Path,
    out: Path,
    modes: list[str],
    top_k: int,
    limit: int = 0,
    query_ir: bool = False,
    contextual: bool = False,
) -> None:
    cases = read_cases(dataset)
    if limit:
        cases = cases[:limit]
    original_flags = {
        "enable_query_ir": settings.enable_query_ir,
        "enable_llm_planner": settings.enable_llm_planner,
        "enable_contextual_retrieval": settings.enable_contextual_retrieval,
    }
    settings.enable_query_ir = query_ir
    settings.enable_llm_planner = False
    settings.enable_contextual_retrieval = contextual
    embedder = get_embedder(
        settings.embedding_model,
        settings.qdrant_vector_size,
        settings.embedding_device,
        settings.embedding_use_fp16,
        settings.embedding_batch_size,
        settings.embedding_max_length,
    )
    bm25 = BM25SparseEncoder(k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len)
    reranker = (
        build_reranker(
            settings.reranker_model,
            path=settings.reranker_path,
            device=settings.reranker_device,
            use_fp16=settings.reranker_use_fp16,
        )
        if "hybrid_rerank" in modes
        else None
    )
    details: list[dict] = []
    try:
        async with SessionLocal() as db:
            for mode in modes:
                for case in cases:
                    try:
                        result = await retrieve(
                            db,
                            case["question"],
                            embedder,
                            bm25,
                            reranker=reranker,
                            top_k=top_k,
                            category=case.get("category"),
                            species=case.get("species"),
                            mode=mode,
                        )
                        ranked_parent = dedupe(
                            [str(item.parent_chunk_id) for item in result.evidence]
                        )
                        ranked_child = dedupe(
                            [str(item.child_chunk_id) for item in result.evidence]
                        )
                        gold_parent = gold_grades(case, "parent")
                        gold_child = gold_grades(case, "child")
                        scored = score_ranking(ranked_parent, gold_parent)
                        child_scored = score_ranking(ranked_child, gold_child)
                        detail = {
                            "id": case["id"],
                            "question": case["question"],
                            "mode": mode,
                            "expect_insufficient": bool(case.get("expect_insufficient")),
                            "refused": not result.sufficient,
                            "reason": result.gate.get("reason"),
                            "sources": len(result.evidence),
                            "retrieval_ms": result.timings.get("retrieval_ms", 0.0),
                            "ranked_chunk_ids": ranked_parent,
                            "ranked_child_ids": ranked_child,
                            "gold": gold_parent,
                            "gold_child": gold_child,
                            **scored,
                            "child_recall@5": child_scored["recall@5"],
                            "child_recall@10": child_scored["recall@10"],
                            "child_ndcg@10": child_scored["ndcg@10"],
                            "child_mrr@10": child_scored["mrr@10"],
                        }
                    except Exception as exc:
                        detail = {
                            "id": case["id"],
                            "question": case["question"],
                            "mode": mode,
                            "expect_insufficient": bool(case.get("expect_insufficient")),
                            "refused": False,
                            "reason": "error",
                            "sources": 0,
                            "retrieval_ms": 0.0,
                            "ranked_chunk_ids": [],
                            "ranked_child_ids": [],
                            "gold": gold_grades(case, "parent"),
                            "gold_child": gold_grades(case, "child"),
                            "first_relevant_rank": None,
                            "mrr@10": 0.0,
                            "recall@5": 0.0,
                            "recall@10": 0.0,
                            "ndcg@5": 0.0,
                            "ndcg@10": 0.0,
                            "gold_rank": {},
                            "child_recall@5": 0.0,
                            "child_recall@10": 0.0,
                            "child_ndcg@10": 0.0,
                            "child_mrr@10": 0.0,
                            "error": f"{exc.__class__.__name__}: {exc}",
                        }
                    details.append(detail)
                    print(
                        f"[{mode}] {case['id']} recall@5={detail['recall@5']} ndcg@5={detail['ndcg@5']}"
                    )
    finally:
        for key, value in original_flags.items():
            setattr(settings, key, value)
        await engine.dispose()

    out.mkdir(parents=True, exist_ok=True)
    with (out / "details.jsonl").open("w", encoding="utf-8") as handle:
        for item in details:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    summary = summarize(details)
    with (out / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "dataset": str(dataset),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "cases": len(cases),
        "modes": modes,
        "top_k": top_k,
        "query_ir": query_ir,
        "query_planner": False,
        "contextual_retrieval": contextual,
        "collection": settings.qdrant_collection,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model if "hybrid_rerank" in modes else None,
        "annotation_status": "ai_assisted_pending_human_review",
        "metric_note": "Primary Recall/nDCG/MRR use the returned parent chunk (the context unit sent to the LLM); child_* metrics use the representative child chunk. Refusals count as zero; insufficient cases are excluded from retrieval means.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "real_questions_v1.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "runs" / "real_questions_v1")
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--query-ir", action="store_true")
    parser.add_argument(
        "--contextual",
        action="store_true",
        help="use context_text for dense indexing (requires the ctx collection)",
    )
    args = parser.parse_args()
    modes = [value.strip() for value in args.modes.split(",") if value.strip()]
    unknown = set(modes) - set(MODES)
    if unknown:
        raise SystemExit(f"unknown modes: {sorted(unknown)}")
    asyncio.run(
        run(
            args.dataset,
            args.out,
            modes,
            args.top_k,
            args.limit,
            args.query_ir,
            args.contextual,
        )
    )


if __name__ == "__main__":
    main()
