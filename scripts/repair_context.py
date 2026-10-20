"""Repair stored heading paths/context_text after a parser heading fix.

This is an in-place metadata repair for existing chunks.  It does not change
chunk IDs, content, ordinals or Qdrant points; run it before rebuilding the
contextual collection.  Default is read-only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.db import SessionLocal
from app.ingestion.context import build_context_text, sanitize_heading_path
from app.models import KbChunk, KbDocument, KbDocumentVersion


async def repair(apply: bool) -> dict:
    changed: list[dict] = []
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(KbChunk, KbDocument.title, KbDocument.species)
                .join(KbDocumentVersion, KbDocumentVersion.id == KbChunk.document_version_id)
                .join(KbDocument, KbDocument.id == KbDocumentVersion.document_id)
                .where(KbDocument.status != "deleted")
                .order_by(KbDocument.title, KbChunk.ordinal)
            )
        ).all()
        for chunk, title, species in rows:
            cleaned = sanitize_heading_path(chunk.heading_path)
            context = build_context_text(
                title=title,
                heading_path=cleaned,
                species=species,
                content=chunk.content,
                block_type=chunk.block_type,
            )
            if cleaned == list(chunk.heading_path or []) and context == chunk.context_text:
                continue
            changed.append(
                {
                    "chunk_id": str(chunk.id),
                    "title": title,
                    "ordinal": chunk.ordinal,
                    "old_heading": list(chunk.heading_path or []),
                    "new_heading": cleaned,
                }
            )
            if apply:
                chunk.heading_path = cleaned
                chunk.context_text = context
        if apply:
            await db.commit()
    return {
        "dry_run": not apply,
        "scanned": len(rows),
        "changed": len(changed),
        "examples": changed[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write repaired metadata")
    args = parser.parse_args()
    result = asyncio.run(repair(args.apply))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
