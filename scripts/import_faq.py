#!/usr/bin/env python3
"""Import public QA candidates into ``faq_entries`` as **pending** rows.

Third-party QA is level 3 material: it may suggest questions and terminology,
but it is never an answer source.  This script therefore:

* writes ``review_status="pending"`` — hard-coded, not configurable;
* never indexes anything into Qdrant;
* records the original model answer separately from ``answer`` so the reviewed
  text can differ from what the dataset said;
* optionally attaches supporting document chunks when a *document* retrieval for
  the same question succeeds, because a FAQ without a traceable support can
  never be verified.

Usage:
    uv run python ../../scripts/import_faq.py --limit 50 --dry-run
    uv run python ../../scripts/import_faq.py --limit 200 --match-evidence
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.faq.normalize import (  # noqa: E402
    content_hash,
    derive_topic,
    domain_relevant,
    normalize_question,
    question_hash,
    screen,
)
from app.models import FaqEntry  # noqa: E402


async def match_evidence(db, question: str, embedder, bm25) -> tuple[list[dict], str]:
    from app.retrieval.service import retrieve

    result = await retrieve(db, question, embedder, bm25, top_k=3)
    if not result.sufficient:
        return [], "none"
    supporting = [
        {
            "document_id": str(item.document_id),
            "version_id": str(item.version_id),
            "chunk_id": str(item.parent_chunk_id),
            "page": item.page,
            "quote": item.quote,
            "score": round(item.score, 6),
            "title": item.title,
            "authority": item.authority,
        }
        for item in result.evidence[:3]
    ]
    return supporting, "supported" if supporting else "none"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidates", default=str(ROOT / "data" / "meta" / "qa_candidates.jsonl")
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--match-evidence", action="store_true")
    parser.add_argument(
        "--include-offtopic",
        action="store_true",
        help="keep rows that fail the aquaculture relevance gate (not recommended)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--report", default=str(ROOT / "data" / "reports" / "faq_import_report.json")
    )
    args = parser.parse_args()

    await init_db()
    path = Path(args.candidates)
    if not path.exists():
        print(f"missing candidates file: {path}", file=sys.stderr)
        return 1

    embedder = bm25 = None
    if args.match_evidence:
        from app.config import settings
        from app.ingestion.embedder import get_embedder
        from app.retrieval.bm25 import BM25SparseEncoder

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

    stats = Counter()
    flag_hist: Counter = Counter()
    imported = 0

    async with SessionLocal() as db:
        for line in path.read_text(encoding="utf-8").splitlines():
            if imported >= args.limit:
                break
            if not line.strip():
                continue
            record = json.loads(line)
            question = (record.get("question") or "").strip()
            answer = (record.get("hf_response") or "").strip()
            if not question or not answer:
                stats["skipped_empty"] += 1
                continue

            norm = normalize_question(question)
            qhash = question_hash(norm)
            exists = await db.scalar(select(FaqEntry.id).where(FaqEntry.question_hash == qhash))
            if exists:
                stats["skipped_duplicate"] += 1
                continue

            relevant, reason = domain_relevant(question)
            if not relevant and not args.include_offtopic:
                stats[f"skipped_{reason}"] += 1
                continue

            flags = screen(question, answer)
            for flag in flags:
                flag_hist[flag] += 1

            species = list(record.get("species") or [])
            supporting, evidence_status = [], "none"
            if args.match_evidence and embedder is not None:
                supporting, evidence_status = await match_evidence(db, question, embedder, bm25)

            entry = FaqEntry(
                question=question,
                answer=answer,
                question_norm=norm,
                question_hash=qhash,
                species=species,
                topic=derive_topic(question, species),
                growth_stages=[],
                region=None,
                source_dataset=record.get("hf_id") or "unknown",
                source_authority="unknown",
                original_id=str(record.get("cid") or "") or None,
                original_source_url=None,
                source_license="cc-by-sa-4.0",
                original_answer=answer,
                supporting=supporting,
                evidence_status=evidence_status,
                quality_flags=flags,
                review_status="pending",  # never changed by the importer
                usage_scope="knowledge",
                confidence=None,
                review_notes="imported from public QA dataset; requires manual review",
                content_hash=content_hash(question, answer),
            )
            if args.dry_run:
                stats["would_import"] += 1
                imported += 1
                if imported <= 5:
                    print(f"[dry-run] {question[:50]} flags={flags}")
                continue

            db.add(entry)
            await db.commit()
            stats["imported"] += 1
            imported += 1
            if imported % 25 == 0:
                print(f"  ... {imported} imported")

    if args.dry_run:
        stats["imported"] = stats.get("would_import", 0)

    report = {
        "at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        "candidates": str(path),
        "stats": dict(stats),
        "quality_flags": dict(flag_hist),
        "review_status": "pending",
        "indexed": 0,
    }
    try:
        async with SessionLocal() as audit_db:
            from app.models import DataRun

            audit_db.add(
                DataRun(
                    kind="faq_import",
                    status="succeeded",
                    params={"candidates": str(path), "limit": args.limit, "match_evidence": args.match_evidence},
                    stats={"imported": stats.get("imported", 0), "indexed": 0, **dict(stats)},
                    finished_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                )
            )
            await audit_db.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"warn: DataRun not recorded: {exc}", file=sys.stderr)

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))