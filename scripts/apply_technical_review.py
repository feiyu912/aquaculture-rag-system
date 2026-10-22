#!/usr/bin/env python3
"""Record *technical* review results for staged documents.

Technical review covers provenance and parse quality only: does the file have
text, are pages locatable, is the text clean, does the section path make sense.
It says nothing about whether the aquaculture content is correct.

Hard rules enforced here:

* ``domain_review_status`` is **never** written.  It stays ``pending`` until a
  human domain reviewer records it elsewhere.
* A document cannot reach ``technical_review_status="pass"`` while it has a
  blocking flag (no text, attachment-only body, OCR garbage).
* Every verdict carries machine-readable flags, so a later reviewer can see
  *why* it was classified without re-reading the PDF.

Usage:
    uv run python ../../scripts/apply_technical_review.py            # dry run
    uv run python ../../scripts/apply_technical_review.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import KbDocument  # noqa: E402

# Manual verdicts that cannot be inferred from the automated scan: the body of
# the document lives in an attachment, so no amount of chunk analysis helps.
MANUAL_FAIL: dict[str, str] = {
    "nftec-tailwater-2026": "body_in_attachment_only",
    "nftec-daoyu-shrimp-draft": "draft_body_in_attachment_only",
    "wf-mangrove-crab": "no_text_layer_scanned_pdf",
    "wf-carp-hatchery-manual": "ocr_garbage_and_word_split",
    "wf-crab-farming": "project_report_duplicate_blocks_year_conflict",
}

NOTICE_HINTS = ("通知", "公告", "函")


def classify(doc: dict) -> tuple[str, list[str]]:
    """Return (status, flags) for one document from the review pack."""
    source_id = doc.get("source_id") or ""
    structure = doc.get("structure") or {}
    flags: list[str] = list(structure.get("anomalies") or [])
    chunks = structure.get("count") or 0

    if source_id in MANUAL_FAIL:
        flags.append(MANUAL_FAIL[source_id])
        return "fail", sorted(set(flags))
    if chunks == 0:
        flags.append("no_chunks")
        return "fail", sorted(set(flags))

    blocking = {
        "no_chunks",
        "ocr_garbage_and_word_split",
        "body_in_attachment_only",
        "draft_body_in_attachment_only",
        "no_text_layer_scanned_pdf",
    }
    if blocking & set(flags):
        return "fail", sorted(set(flags))

    # A very small chunk count on a "standard"-looking page usually means the
    # real content is an attachment, not text.
    if chunks <= 5 and "附件" in (doc.get("first_paragraph") or ""):
        flags.append("possibly_attachment_only")
        return "fail", sorted(set(flags))

    # These are normal consequences of parent-child chunking with page ranges,
    # not quality defects; they stay in the flag list as information only.
    informational = ("cross_page_chunk", "chunk_under_40_chars", "has_markdown_tables")
    substantive = [f for f in flags if not f.startswith(informational)]

    # NOTE: lower_start_pct was removed. An English chunk may legitimately begin
    # mid-sentence after the overlap window snaps to a word boundary, so the
    # metric produced false positives. Real word cuts need source character
    # offsets (start_char/end_char), which are tracked separately.
    if any(
        f.startswith(("duplicate_chunk_text", "navigation_boilerplate", "heading_pollution", "low_chunk_density", "table_heavy"))
        for f in flags
    ):
        return "warn", sorted(set(flags))
    if substantive:
        return "warn", sorted(set(flags))
    return "pass", []


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", default=str(ROOT / "data" / "reports" / "review_pack.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    pack = json.loads(Path(args.pack).read_text(encoding="utf-8"))
    docs = pack.get("documents") or []
    if not docs:
        print("empty review pack", file=sys.stderr)
        return 2

    await init_db()
    report = []
    async with SessionLocal() as db:
        for item in docs:
            source_id = item.get("source_id")
            row = (
                await db.execute(
                    select(KbDocument).where(KbDocument.doc_metadata["source_id"].astext == source_id)
                )
            ).scalars().first()
            if row is None:
                report.append({"source_id": source_id, "status": "missing_row"})
                continue
            status, flags = classify(item)
            report.append(
                {
                    "source_id": source_id,
                    "title": row.title,
                    "technical_review_status": status,
                    "domain_review_status": row.domain_review_status,
                    "flags": flags,
                }
            )
            if args.apply:
                row.technical_review_status = status
                row.review_flags = flags
                row.reviewed_at = datetime.now(UTC)
                # intentionally NOT touching domain_review_status
        if args.apply:
            await db.commit()

    out = ROOT / "data" / "reports" / "technical_review_report.json"
    out.write_text(json.dumps({"applied": args.apply, "documents": report}, ensure_ascii=False, indent=2), encoding="utf-8")

    tally = {"pass": 0, "warn": 0, "fail": 0}
    for item in report:
        tally[item["technical_review_status"]] = tally.get(item["technical_review_status"], 0) + 1
        print(f"{item['technical_review_status']:<5} {item['source_id']:<28} {'; '.join(item['flags'])[:80]}")
    print(f"\npass={tally['pass']} warn={tally['warn']} fail={tally['fail']} applied={args.apply}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))