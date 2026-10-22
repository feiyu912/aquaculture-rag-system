#!/usr/bin/env python3
"""In-process answer-quality evaluation: rule IR vs LLM planner IR.

This runs the *real* retrieval + generation chain (BGE-M3 → Qdrant dense/BM25 →
RRF → BGE reranker → OpenAI-compatible LLM) without going through the HTTP API,
so it can be reproduced while a dev server is serving the frontend.

It measures what can be measured deterministically — answer presence, citation
existence/coverage, whether a cited source is the gold document, latency — and
writes them next to the answers.  It does **not** claim factual correctness:
that needs blinded human review.  The script refuses to run against the mock
generator, so a missing API key fails loudly instead of producing fake answers.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings
from app.db import SessionLocal
from app.generation.citations import validate_answer
from app.generation.llm import Generator, LLMError, MockGenerator, build_generator
from app.ingestion.embedder import get_embedder
from app.query.planner import planner_from_generator
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.rerank import build_reranker
from app.retrieval.service import Evidence, retrieve

FAMILIES = ("rules", "llm")


def read_cases(path: Path, ids: list[str], limit: int) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        case = json.loads(line)
        if ids and case.get("id") not in ids:
            continue
        cases.append(case)
    return cases[:limit] if limit else cases


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str | None:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True
            ).strip()
            or None
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def _gold_source_hit(evidence: list[Evidence], cited: list[int], gold_titles: list[str]) -> bool:
    if not cited or not gold_titles:
        return False
    by_index = {item.source_index: item.title for item in evidence}
    for index in cited:
        title = by_index.get(index)
        if title and any(gold in title or title in gold for gold in gold_titles):
            return True
    return False


async def _generate(generator: Generator, question: str, evidence: list[Evidence]) -> str:
    last: Exception | None = None
    for attempt in range(3):
        try:
            answer = ""
            async for token in generator.stream(question, evidence):
                answer += token
            return answer
        except LLMError as exc:  # gateway timeouts are transient; retry twice
            last = exc
            await asyncio.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]


async def run(
    cases: list[dict],
    mode: str,
    top_k: int,
    out: Path,
    max_sources: int,
    concurrency: int = 4,
    families: tuple[str, ...] = ("rules",),
) -> dict:
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
    if isinstance(generator, MockGenerator):
        raise SystemExit(
            "refusing to evaluate with MockGenerator; configure a real OpenAI-compatible LLM"
        )
    planner = planner_from_generator(generator)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(case: dict, family: str) -> dict:
        async with semaphore, SessionLocal() as db:
            started = time.perf_counter()
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
            retrieval_ms = (time.perf_counter() - started) * 1000
            evidence = result.evidence[:max_sources]
            for index, item in enumerate(evidence, start=1):
                item.source_index = index
            gold_ids = {str(value) for value in (case.get("gold_chunk_ids") or [])}
            gold_pages = {int(value) for value in (case.get("gold_pages") or [])}
            record: dict = {
                "sufficient": result.sufficient,
                "gate_reason": result.gate.get("reason"),
                "sources": len(evidence),
                "source_titles": [item.title for item in evidence],
                "evidence_parent_ids": [str(item.parent_chunk_id) for item in evidence],
                "evidence_pages": [item.page for item in evidence],
                "gold_in_evidence": (
                    any(str(item.parent_chunk_id) in gold_ids for item in evidence)
                    if gold_ids
                    else None
                ),
                "gold_page_in_evidence": (
                    any(item.page in gold_pages for item in evidence) if gold_pages else None
                ),
                "retrieval_ms": round(retrieval_ms, 1),
                "planner": (result.config or {}).get("llm_planner"),
            }
            if not result.sufficient or not evidence:
                record.update(
                    answered=False,
                    answer="",
                    answer_chars=0,
                    citation_coverage=0.0,
                    cited_indices=[],
                    invalid_citations=[],
                    gold_source_cited=False,
                    generation_ms=0.0,
                )
                return record
            gen_started = time.perf_counter()
            answer = await _generate(generator, case["question"], evidence)
            record["generation_ms"] = round((time.perf_counter() - gen_started) * 1000, 1)
            report = validate_answer(answer, len(evidence))
            record.update(
                answered=bool(answer.strip()),
                answer=answer,
                answer_chars=len(answer),
                citation_coverage=report.coverage,
                cited_indices=report.cited_indices,
                invalid_citations=report.invalid_indices,
                gold_source_cited=_gold_source_hit(
                    evidence, report.cited_indices, case.get("gold_titles") or []
                ),
            )
            return record

    results: dict[str, dict] = {case["id"]: {} for case in cases}
    for family in families:
        settings.enable_llm_planner = family == "llm"
        family_records = await asyncio.gather(*(one(case, family) for case in cases))
        for case, record in zip(cases, family_records, strict=True):
            results[case["id"]][family] = record
            print(
                f"{case['id']} {family} sufficient={record['sufficient']} "
                f"answer={record.get('answer_chars', 0)}c "
                f"cov={record.get('citation_coverage', 0):.2f} "
                f"gold_src={record.get('gold_source_cited')} "
                f"planner={(record.get('planner') or {}).get('used_llm')}",
                flush=True,
            )
    details = [
        {"id": case["id"], "question": case["question"], **results[case["id"]]}
        for case in cases
    ]
    settings.enable_llm_planner = False

    summary: dict = {
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "dataset": str(ROOT / "eval" / "real_questions_v1.jsonl"),
        "mode": mode,
        "top_k": top_k,
        "max_sources": max_sources,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.openai_model or settings.deepseek_model,
        "families": {},
    }
    for family in families:
        rows = [row[family] for row in details]
        answered = [row for row in rows if row["answered"]]
        summary["families"][family] = {
            "cases": len(rows),
            "answered": len(answered),
            "refused": len(rows) - len(answered),
            "citation_coverage_mean": round(
                statistics.fmean(row["citation_coverage"] for row in rows), 4
            )
            if rows
            else 0.0,
            "invalid_citation_cases": sum(1 for row in rows if row["invalid_citations"]),
            "gold_source_cited": sum(1 for row in rows if row["gold_source_cited"]),
            "gold_in_evidence": sum(1 for row in rows if row.get("gold_in_evidence")),
            "gold_page_in_evidence": sum(1 for row in rows if row.get("gold_page_in_evidence")),
            "avg_sources": round(statistics.fmean(row["sources"] for row in rows), 2) if rows else 0.0,
            "avg_answer_chars": round(statistics.fmean(row.get("answer_chars", 0) for row in rows), 1)
            if rows
            else 0.0,
            "avg_retrieval_ms": round(statistics.fmean(row["retrieval_ms"] for row in rows), 1)
            if rows
            else 0.0,
            "avg_generation_ms": round(statistics.fmean(row["generation_ms"] for row in rows), 1)
            if rows
            else 0.0,
        }

    out.mkdir(parents=True, exist_ok=True)
    (out / "details.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in details) + "\n",
        encoding="utf-8",
    )
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "real_questions_v1.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "runs" / "answer_quality")
    parser.add_argument("--ids", default="", help="comma-separated case ids")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--mode", default="hybrid_rerank")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-sources", type=int, default=settings.max_sources)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--families",
        default="rules",
        help="comma-separated: rules,llm",
    )
    args = parser.parse_args()
    ids = [value.strip() for value in args.ids.split(",") if value.strip()]
    cases = read_cases(args.dataset, ids, args.limit)
    if not cases:
        raise SystemExit("no matching cases")
    summary = asyncio.run(
        run(
            cases,
            args.mode,
            args.top_k,
            args.out,
            args.max_sources,
            args.concurrency,
            tuple(value.strip() for value in args.families.split(",") if value.strip()),
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()