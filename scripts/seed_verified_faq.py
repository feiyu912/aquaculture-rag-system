#!/usr/bin/env python3
"""Seed a small number of verified FAQ from **active** document chunks.

Purpose: make the B (document + verified FAQ) experiment meaningful.  Each
seeded entry copies its answer text verbatim from one chunk of an already
published document, records that chunk as its support, and then goes through the
same :func:`app.faq.review.verify_faq` path a human reviewer would use — so the
seed cannot bypass the verification rules it is meant to exercise.

Usage:
    uv run python ../../scripts/seed_verified_faq.py --dry-run
    uv run python ../../scripts/seed_verified_faq.py
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.faq.normalize import content_hash, normalize_question, question_hash  # noqa: E402
from app.faq.review import ReviewError, verify_faq  # noqa: E402
from app.models import FaqEntry, KbChunk, KbDocument, KbDocumentVersion  # noqa: E402

# (document title fragment, question, chunk search terms)
SEEDS = [
    ("DB36", "扣蟹培育池塘的溶氧量应保持在多少以上？", ["溶氧量"]),
    ("DB36", "扣蟹培育的适宜 pH 范围是多少？", ["pH"]),
    ("DB36", "河蟹扣蟹培育池塘的水深要求是多少？", ["水深"]),
    ("DB46", "凡纳滨对虾养殖用水的处理要求是什么？", ["砂滤"]),
    ("DB46", "对虾养殖池塘清塘消毒可使用什么物质？", ["石灰"]),
    ("DB32", "河蟹交配的适宜水温是多少？", ["适宜水温"]),
]

SENTENCE_END = re.compile(r"(?<=[。；;！？!?])")


def excerpt_around(content: str, term: str, limit: int = 240) -> str:
    """Return the sentence containing ``term`` (plus the next one if short).

    Copying the containing sentence is what makes the seeded FAQ traceable: the
    answer is not paraphrased, so a reviewer can diff it against the chunk.
    """
    index = content.find(term)
    if index < 0:
        return content[:limit].strip()
    bounds = [0] + [m.end() for m in SENTENCE_END.finditer(content)] + [len(content)]
    for i in range(len(bounds) - 1):
        if bounds[i] <= index < bounds[i + 1]:
            text = content[bounds[i] : bounds[i + 1]]
            if len(text) < limit // 2 and i + 2 < len(bounds):
                text += content[bounds[i + 1] : bounds[i + 2]]
            return text.strip()
    return content[:limit].strip()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reviewer", default="thesis-author")
    args = parser.parse_args()

    await init_db()
    created = verified = 0
    async with SessionLocal() as db:
        for title_fragment, question, terms in SEEDS:
            doc = (
                await db.execute(
                    select(KbDocument).where(
                        KbDocument.title.like(f"%{title_fragment}%"),
                        KbDocument.status == "active",
                        KbDocument.current_version_id.is_not(None),
                    )
                )
            ).scalars().first()
            if doc is None:
                print(f"skip (no active doc): {title_fragment}")
                continue
            version = await db.get(KbDocumentVersion, doc.current_version_id)
            chunk = None
            for term in terms:
                chunk = (
                    await db.execute(
                        select(KbChunk)
                        .where(
                            KbChunk.document_version_id == version.id,
                            KbChunk.chunk_role == "child",
                            KbChunk.content.ilike(f"%{term}%"),
                        )
                        .order_by(KbChunk.page_from, KbChunk.ordinal)
                    )
                ).scalars().first()
                if chunk is not None:
                    break
            if chunk is None:
                print(f"skip (no matching chunk): {title_fragment} {terms}")
                continue

            answer = excerpt_around(chunk.content, terms[0])
            norm = normalize_question(question)
            qhash = question_hash(norm)
            existing = await db.scalar(select(FaqEntry.id).where(FaqEntry.question_hash == qhash))
            if existing:
                print(f"skip (exists): {question}")
                continue

            entry = FaqEntry(
                question=question,
                answer=answer,
                question_norm=norm,
                question_hash=qhash,
                species=list(doc.species or []),
                topic=None,
                growth_stages=list(doc.growth_stages or []),
                region=doc.region,
                source_dataset="seed:active-document",
                source_authority=doc.authority_level,
                original_id="seed",
                original_source_url=doc.source_url,
                source_license=None,
                original_answer=answer,
                supporting=[
                    {
                        "document_id": str(doc.id),
                        "version_id": str(version.id),
                        "chunk_id": str(chunk.id),
                        "page": chunk.page_from,
                        "quote": excerpt_around(chunk.content, terms[0], 120),
                        "authority": doc.authority_level,
                        "title": doc.title,
                    }
                ],
                evidence_status="supported",
                quality_flags=["seeded_from_active_document"],
                review_status="pending",
                usage_scope="knowledge",
                review_notes="seeded from active document chunk; answer copied verbatim",
                content_hash=content_hash(question, answer),
            )
            created += 1
            if args.dry_run:
                print(f"[dry-run] {question} -> {doc.title} p{chunk.page_from}")
                print(f"          answer: {answer[:80]}")
                continue
            db.add(entry)
            await db.commit()
            try:
                await verify_faq(
                    db,
                    entry,
                    reviewer=args.reviewer,
                    notes="seeded fixture: answer copied verbatim from supporting chunk",
                )
                verified += 1
                print(f"verified {question} -> {doc.title} p{chunk.page_from}")
            except ReviewError as exc:
                print(f"verify failed ({exc.status_code}): {question} :: {exc.detail}")

    print(f"\ncreated={created} verified={verified}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))