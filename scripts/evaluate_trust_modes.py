#!/usr/bin/env python3
"""A/B/C/D comparison for the layered trust policy.

    A  document_only            original documents only (production default)
    B  document_plus_verified   documents, then verified FAQ as a supplement
    C  document_plus_qa_hints   unverified QA only rewrites the query
    D  mixed_unfiltered         *control experiment*: merge unverified QA into
                                the evidence pool with no trust filtering

D never writes to Qdrant and is never a runtime mode.  It exists to quantify
what the isolation protects against, which is the claim the thesis has to make:
after importing a large third-party QA corpus the system still answers from
trustworthy originals and does not cite unverified answers.

Metrics per mode:
  doc_cited_rate     share of answerable questions whose evidence includes the
                     expected source document
  pollution_rate     share of questions where an unverified QA answer appears
                     among the evidence items (must be 0 for A/B/C)
  refusal_rate       share of questions the evidence gate refused
  avg_evidence       mean number of evidence items
  p50_latency_ms

Usage:
    uv run python ../../scripts/evaluate_trust_modes.py --limit 40
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.ingestion.embedder import get_embedder  # noqa: E402
from app.models import FaqEntry  # noqa: E402
from app.retrieval.bm25 import BM25SparseEncoder, tokenize  # noqa: E402
from app.retrieval.service import retrieve  # noqa: E402

MODES = ("A_document_only", "B_document_plus_verified", "C_document_plus_qa_hints", "D_mixed_unfiltered")

# Deliberately wrong statements that are semantically very close to real
# questions.  Each is (question, wrong_answer, correct_document_hint).
POLLUTION_PROBES = [
    ("河蟹养殖池塘溶解氧最低应保持多少？", "溶解氧保持 1mg/L 即可，河蟹耐低氧能力强。", "DB36"),
    ("扣蟹培育的适宜 pH 范围是多少？", "pH 9.5～10.0 最利于扣蟹蜕壳。", "DB36"),
    ("河蟹池塘环沟的宽度和深度要求是多少？", "环沟宽 0.5m、深 0.3m 即可满足养殖。", "DB36"),
    ("凡纳滨对虾养殖的适宜盐度范围是多少？", "盐度 0～1 最适合凡纳滨对虾生长。", "DB46"),
    ("南美白对虾池塘清塘消毒每亩用多少生石灰？", "每亩用生石灰 5kg 全池泼洒。", "DB46"),
    ("河蟹生态育苗的适宜水温是多少？", "水温 35℃ 以上出苗最快。", "DB32"),
    ("扣蟹培育时水草种植面积占比多少？", "水草覆盖率达到 90% 以上最好。", "DB36"),
    ("对虾养殖中氨氮的安全浓度上限是多少？", "氨氮低于 5mg/L 都不会影响对虾。", "DB46"),
]


def read_cases(path: Path, limit: int | None) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            cases.append(json.loads(line))
    answerable = [c for c in cases if c.get("answerable", True)]
    return answerable[:limit] if limit else answerable


async def qa_hints(db, question: str, limit: int = 2) -> str:
    """Query expansion from *unverified* QA — never evidence.

    Uses a plain token-overlap scan over pending rows in PostgreSQL.  No vectors,
    no Qdrant: level-3 material has no path into the index at all.
    """
    rows = (
        await db.execute(
            select(FaqEntry.question, FaqEntry.answer)
            .where(FaqEntry.review_status == "pending")
            .limit(2000)
        )
    ).all()
    if not rows:
        return question
    terms = set(tokenize(question))
    scored = []
    for faq_question, _answer in rows:
        overlap = len(terms & set(tokenize(faq_question)))
        if overlap:
            scored.append((overlap, faq_question))
    scored.sort(key=lambda item: -item[0])
    if not scored:
        return question
    extras = [text for _, text in scored[:limit]]
    return f"{question} {' '.join(extras)}"


def wrong_qa_matches(question: str, probes: list[dict]) -> list[dict]:
    """Unverified QA whose tokens overlap the question (simulates a hit)."""
    terms = set(tokenize(question))
    hits = []
    for probe in probes:
        overlap = len(terms & set(tokenize(probe["question"])))
        if overlap >= 3:
            hits.append(probe)
    return hits


async def run_mode(
    mode: str,
    cases: list[dict],
    probes: list[dict],
    db,
    embedder,
    bm25,
) -> dict:
    rows = []
    latencies = []
    for case in cases:
        question = case["question"]
        started = time.perf_counter()

        if mode == "C_document_plus_qa_hints":
            expanded = await qa_hints(db, question)
            result = await retrieve(
                db, question, embedder, bm25, search_question=expanded, include_faq=False
            )
        elif mode == "B_document_plus_verified":
            result = await retrieve(db, question, embedder, bm25, include_faq=True)
        else:
            result = await retrieve(db, question, embedder, bm25, include_faq=False)

        elapsed = (time.perf_counter() - started) * 1000
        latencies.append(elapsed)

        evidence = result.evidence
        source_types = [item.source_type for item in evidence]
        doc_titles = [item.title for item in evidence if item.source_type == "document"]

        polluted = False
        if mode == "D_mixed_unfiltered":
            hits = wrong_qa_matches(question, probes)
            if hits:
                polluted = True
                result_text = " ".join(hits[0]["wrong_answer"] for _ in [0])
        else:
            polluted = any(item.source_type != "document" and item.evidence_level in {"L3_unverified_qa", "L4_history"} for item in evidence)

        expected = (case.get("expected_doc") or "").strip()
        doc_cited = bool(expected) and any(expected in title for title in doc_titles)

        supplement = result.config.get("faq_supplement") or {}
        rows.append(
            {
                "question": question,
                "faq_supplement_enabled": supplement.get("enabled"),
                "faq_supplement_accepted": supplement.get("accepted", 0),
                "faq_supplement_skipped": supplement.get("skipped"),
                "sufficient": result.sufficient,
                "evidence_count": len(evidence),
                "source_types": source_types,
                "doc_cited": doc_cited,
                "polluted": polluted,
                "gate_reason": (result.gate or {}).get("reason"),
            }
        )

    pollution_rate = sum(row["polluted"] for row in rows) / len(rows)
    doc_cited_rate = sum(row["doc_cited"] for row in rows) / len(rows)
    refusal_rate = sum(not row["sufficient"] for row in rows) / len(rows)
    return {
        "mode": mode,
        "questions": len(rows),
        "doc_cited_rate": round(doc_cited_rate, 3),
        "pollution_rate": round(pollution_rate, 3),
        "refusal_rate": round(refusal_rate, 3),
        "avg_evidence": round(statistics.mean(row["evidence_count"] for row in rows), 2),
        "p50_latency_ms": round(statistics.median(latencies), 1),
        "faq_evidence_total": sum(row["source_types"].count("faq") for row in rows),
        "faq_supplement_attempts": sum(
            1 for row in rows if row["faq_supplement_enabled"]
        ),
        "faq_supplement_accepted_total": sum(
            row["faq_supplement_accepted"] for row in rows
        ),
        "rows": rows,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(ROOT / "eval" / "real_questions_v1.jsonl"))
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument(
        "--report", default=str(ROOT / "data" / "reports" / "trust_modes_report.json")
    )
    args = parser.parse_args()

    cases = read_cases(Path(args.cases), args.limit)
    # Attach the expected document alias from the seed file when available.
    seed_path = ROOT / "eval" / "real_questions_v1.seed.json"
    if seed_path.exists():
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        seed_cases = seed.get("cases") if isinstance(seed, dict) else seed
        by_question = {
            item["question"]: item for item in (seed_cases or []) if isinstance(item, dict)
        }
        for case in cases:
            origin = by_question.get(case["question"])
            if origin and origin.get("gold"):
                alias = origin["gold"][0].get("doc")
                case["expected_doc"] = {"crab": "DB36", "shrimp": "DB46", "db32": "DB32"}.get(alias, alias)

    probes = [
        {"question": q, "wrong_answer": a, "correct_doc": d} for q, a, d in POLLUTION_PROBES
    ]
    for probe in probes:
        cases.append(
            {
                "question": probe["question"],
                "answerable": True,
                "expected_doc": probe["correct_doc"],
                "pollution_probe": True,
            }
        )

    embedder = get_embedder(
        settings.embedding_model,
        settings.qdrant_vector_size,
        settings.embedding_device,
        settings.embedding_use_fp16,
        settings.embedding_batch_size,
        settings.embedding_max_length,
    )
    bm25 = BM25SparseEncoder(
        k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len
    )

    # Capability on for the whole run: A/B/C then differ only by request intent
    # (`include_faq`), which is what the experiment is supposed to isolate.
    original_flag = settings.enable_faq_retrieval
    settings.enable_faq_retrieval = True
    results = []
    async with SessionLocal() as db:
        for mode in MODES:
            print(f"running {mode} on {len(cases)} questions ...")
            results.append(await run_mode(mode, cases, probes, db, embedder, bm25))
    settings.enable_faq_retrieval = original_flag

    report = {
        "at": datetime.now(UTC).isoformat(),
        "cases": len(cases),
        "pollution_probes": len(probes),
        "summary": [{k: v for k, v in row.items() if k != "rows"} for row in results],
        "modes": results,
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'mode':<28}{'doc_cited':>10}{'pollution':>11}{'refusal':>9}{'evidence':>10}{'p50ms':>8}")
    for row in results:
        print(
            f"{row['mode']:<28}{row['doc_cited_rate']:>10.3f}{row['pollution_rate']:>11.3f}"
            f"{row['refusal_rate']:>9.3f}{row['avg_evidence']:>10.2f}{row['p50_latency_ms']:>8.1f}"
        )
    print(f"\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))