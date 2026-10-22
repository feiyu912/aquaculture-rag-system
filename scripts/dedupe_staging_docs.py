#!/usr/bin/env python3
"""Remove duplicate staging documents created by repeated --force ingests.

A rerun of ``ingest_inbox.py --force`` created a *new* ``kb_documents`` row each
time instead of a new version, so the same source now has several staging rows
with identical content.  This script keeps one row per (source_id, sha256) and
deletes the rest, including their versions, chunks and Qdrant points.

Dry run by default; ``--apply`` performs the deletion.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import delete, select, text  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import KbChunk, KbDocument, KbDocumentVersion  # noqa: E402
from app.retrieval.vector_store import get_client  # noqa: E402
from qdrant_client import models as qmodels  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    await init_db()
    async with SessionLocal() as db:
        docs = (await db.execute(select(KbDocument).where(KbDocument.status == "staging"))).scalars().all()
        # Content identity must come from the parsed version's content_hash.
        # doc_metadata rarely carries sha256, and grouping on a None hash
        # collapses every document of one source into a single "duplicate"
        # group -- that mistake once deleted 197 distinct documents.
        version_hash: dict = {}
        for vid, chash in (await db.execute(
            text("SELECT id, content_hash FROM kb_document_versions")
        )).all():
            version_hash[vid] = chash

        groups: dict[tuple, list[KbDocument]] = defaultdict(list)
        skipped_no_hash = 0
        for doc in docs:
            meta = doc.doc_metadata or {}
            chash = version_hash.get(doc.current_version_id) or meta.get("sha256")
            if not chash:
                skipped_no_hash += 1
                continue                      # never group on a missing hash
            groups[(meta.get("source_id"), chash)].append(doc)
        if skipped_no_hash:
            print(f"skipped {skipped_no_hash} staging docs with no content hash")

        dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
        print(f"staging docs={len(docs)} groups={len(groups)} duplicated_groups={len(dup_groups)}")
        removed = 0
        for (source_id, sha), items in sorted(dup_groups.items(), key=lambda kv: str(kv[0])):
            items.sort(key=lambda d: d.created_at, reverse=True)  # keep the newest (fixed parser)
            keep, extra = items[0], items[1:]
            print(f"  {source_id}: keep={keep.id} drop={len(extra)}")
            removed += len(extra)
        if not dup_groups:
            print("nothing to do")
            return 0

        if not args.apply:
            print(f"\nwould delete {removed} duplicate document(s); rerun with --apply")
            return 0

        client = get_client()
        try:
            for (source_id, sha), items in dup_groups.items():
                items.sort(key=lambda d: d.created_at, reverse=True)
                for doc in items[1:]:
                    versions = (await db.execute(
                        select(KbDocumentVersion).where(KbDocumentVersion.document_id == doc.id)
                    )).scalars().all()
                    for version in versions:
                        client.delete(
                            collection_name="kb_chunks_bge_m3_v1",
                            points_selector=qmodels.FilterSelector(
                                filter=qmodels.Filter(
                                    must=[
                                        qmodels.FieldCondition(
                                            key="document_version_id",
                                            match=qmodels.MatchValue(value=str(version.id)),
                                        )
                                    ]
                                )
                            ),
                        )
                        await db.execute(delete(KbChunk).where(KbChunk.document_version_id == version.id))
                        await db.delete(version)
                    await db.delete(doc)
            await db.commit()
        finally:
            client.close()
        print(f"deleted {removed} duplicate document(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
