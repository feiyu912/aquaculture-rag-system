#!/usr/bin/env python3
"""Reconcile data_items with kb_documents by content hash.

`ingest_inbox.py` does not know about ``data_items``; this pass closes the loop so
discovery → download → parse → review can be read from one table.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import text  # noqa: E402


async def main() -> int:
    from app.db import SessionLocal, init_db

    await init_db()
    async with SessionLocal() as db:
        linked = await db.execute(text("""
            UPDATE data_items i
            SET document_id = d.id, state = 'staging', updated_at = now()
            FROM kb_documents d
            JOIN kb_document_versions v ON v.id = d.current_version_id
            WHERE i.sha256 IS NOT NULL
              AND i.sha256 = v.content_hash
              AND i.state IN ('downloaded','selected','discovered')
        """))
        nohash = await db.execute(text("""
            UPDATE data_items i
            SET document_id = d.id, state = 'staging', updated_at = now()
            FROM kb_documents d
            JOIN kb_document_versions v ON v.id = d.current_version_id
            WHERE i.sha256 IS NULL
              AND d.metadata->>'source_id' = i.source_id
              AND i.state = 'failed'
              AND d.status = 'staging'
        """))
        await db.commit()
        rows = (await db.execute(text(
            "SELECT state, count(*) FROM data_items GROUP BY 1 ORDER BY 2 DESC"
        ))).all()
        print("linked_by_hash", linked.rowcount, "linked_by_source", nohash.rowcount)
        print("data_items", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
