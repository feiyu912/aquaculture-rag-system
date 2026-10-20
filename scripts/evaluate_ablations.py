"""Run retrieval-module ablations directly against the service (no API needed).

Contextual Retrieval is evaluated as a separate index run: pass
``--contextual --collection <ctx_collection>`` so the query-time flag matches
the context-aware vectors.  It is not mixed into the normal configs.  Every
other optional module, including adaptive routing, can be toggled here.

Outputs:
  details.jsonl  one row per case/config, for error analysis
  summary.csv    aggregate metrics per config
  manifest.json  commit, dataset hash, model/config snapshot
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings
from app.db import SessionLocal, engine
from app.evaluation.ablations import (
    DEFAULT_CONFIGS,
    apply_config,
    restore_flags,
    snapshot_flags,
    summarize,
    validate_cases,
)
from app.ingestion.embedder import get_embedder
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.rerank import build_reranker
from app.retrieval.service import retrieve


def read_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    return cases


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


def dataset_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run_case(db, embedder, bm25, case: dict, mode: str, reranker=None) -> dict:
    result = await retrieve(
        db,
        case["question"],
        embedder,
        bm25,
        reranker=reranker,
        category=case.get("category"),
        species=case.get("species"),
        mode=mode,
    )
    gold_title = case.get("gold_title")
    gold_pages = set(case.get("gold_pages") or [])
    hit_rank = None
    for rank, item in enumerate(result.evidence, start=1):
        if item.title == gold_title and item.page in gold_pages:
            hit_rank = rank
            break
    return {
        "id": case["id"],
        "question": case["question"],
        "hit": hit_rank is not None,
        "hit_rank": hit_rank,
        "mrr": round(1.0 / hit_rank, 4) if hit_rank else 0.0,
        "refused": not result.sufficient,
        "sources": len(result.evidence),
        "reason": result.gate.get("reason"),
        "route": result.config.get("adaptive_route"),
        "modules": result.config.get("adaptive_modules"),
        "queries": len((result.rankings or {}).get("queries") or []),
        "targeted": bool(result.config.get("targeted_retrieval")),
        "reranker": result.config.get("reranker"),
        "retrieval_ms": result.timings.get("retrieval_ms", 0.0),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "eval" / "sample_questions.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "runs" / "ablations"))
    parser.add_argument("--mode", default="hybrid")
    parser.add_argument(
        "--contextual",
        action="store_true",
        help="query a context-aware index; requires --collection",
    )
    parser.add_argument(
        "--collection",
        default="",
        help="override QDRANT_COLLECTION (required with --contextual)",
    )
    parser.add_argument("--configs", default="", help="comma-separated config names")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    cases = read_cases(dataset_path)
    if args.limit:
        cases = cases[: args.limit]
    errors = validate_cases(cases)
    if errors:
        print(json.dumps({"dataset_errors": errors}, ensure_ascii=False, indent=2))
        return 2
    if args.contextual and not args.collection:
        print("--contextual requires --collection", file=sys.stderr)
        return 2
    if args.collection:
        settings.qdrant_collection = args.collection
    if args.contextual:
        settings.enable_contextual_retrieval = True

    names = [name.strip() for name in args.configs.split(",") if name.strip()]
    if names:
        unknown = set(names) - set(DEFAULT_CONFIGS)
        if unknown:
            raise SystemExit(f"unknown configs: {sorted(unknown)}")
        configs = {name: DEFAULT_CONFIGS[name] for name in names}
    else:
        configs = DEFAULT_CONFIGS

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    details: list[dict] = []
    rows: list[dict] = []
    original_flags = snapshot_flags(settings)
    embedder = get_embedder(
        settings.embedding_model,
        settings.qdrant_vector_size,
        settings.embedding_device,
        settings.embedding_use_fp16,
        settings.embedding_batch_size,
        settings.embedding_max_length,
    )
    bm25 = BM25SparseEncoder(k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len)
    reranker = None
    if args.mode == "hybrid_rerank":
        reranker = build_reranker(
            settings.reranker_model,
            path=settings.reranker_path,
            device=settings.reranker_device,
            use_fp16=settings.reranker_use_fp16,
        )

    try:
        async with SessionLocal() as db:
            for name, overrides in configs.items():
                apply_config(settings, overrides)
                case_details = []
                for case in cases:
                    try:
                        detail = await run_case(
                            db, embedder, bm25, case, args.mode, reranker=reranker
                        )
                    except Exception as exc:  # keep other configs/cases measurable
                        detail = {
                            "id": case["id"],
                            "question": case["question"],
                            "hit": False,
                            "hit_rank": None,
                            "mrr": 0.0,
                            "refused": False,
                            "sources": 0,
                            "reason": "error",
                            "route": None,
                            "modules": None,
                            "queries": 0,
                            "targeted": False,
                            "reranker": None,
                            "retrieval_ms": 0.0,
                            "error": f"{exc.__class__.__name__}: {exc}",
                        }
                    detail["config"] = name
                    case_details.append(detail)
                    details.append(detail)
                rows.append(summarize(name, case_details, cases))
    finally:
        restore_flags(settings, original_flags)
        await engine.dispose()

    with (out_dir / "details.jsonl").open("w", encoding="utf-8") as handle:
        for detail in details:
            handle.write(json.dumps(detail, ensure_ascii=False) + "\n")

    with (out_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "dataset": str(dataset_path),
        "dataset_sha256": dataset_digest(dataset_path),
        "cases": len(cases),
        "mode": args.mode,
        "collection": settings.qdrant_collection,
        "contextual": settings.enable_contextual_retrieval,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "python_version": platform.python_version(),
        "original_flags": original_flags,
        "configs": {name: overrides for name, overrides in configs.items()},
        "outputs": ["details.jsonl", "summary.csv", "manifest.json"],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
