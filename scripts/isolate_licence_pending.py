#!/usr/bin/env python3
"""Isolate documents that lack an approved licence basis — reversibly.

Isolation means three things, none of which destroys evidence:

  * index_eligibility becomes 'pending_licence' (or 'ineligible' when the
    technical review failed), so the publish gate and the retrieval guard both
    refuse the document;
  * the derived Qdrant points for its current version are deleted, so the
    formal index only contains servable material;
  * metadata.licence_isolation records when, why and under which review scope
    it happened.  Rows, source URLs, original files and licence evidence stay.

Deleting points is reversible because PostgreSQL keeps the chunks: `--restore`
re-embeds and re-upserts exactly the versions listed in the isolation report,
but only for documents whose licence review is now 'approved'.

Run without --apply for a dry run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

TARGETS_SQL = """
SELECT d.id, d.title, d.source_org, d.current_version_id, d.index_eligibility,
       d.technical_review_status, r.scope AS review_scope, r.decision AS review_decision,
       (SELECT count(*) FROM kb_chunks ch
        WHERE ch.document_version_id = d.current_version_id
          AND ch.chunk_role = 'child') AS child_chunks
FROM kb_documents d
LEFT JOIN licence_reviews r ON r.id = d.licence_review_id
WHERE d.status = 'active'
  AND d.current_version_id IS NOT NULL
  AND (
        d.index_eligibility IS DISTINCT FROM 'eligible'
        OR d.technical_review_status = 'fail'
        OR d.source_trust IS NULL
        OR d.source_trust = 'unknown'
        OR r.decision IS DISTINCT FROM 'approved'
      )
ORDER BY d.id
"""


def target_eligibility(row: dict) -> str:
    return "ineligible" if row["technical_review_status"] == "fail" else "pending_licence"


def isolation_reason(row: dict) -> str:
    if row["technical_review_status"] == "fail":
        return "technical_review_failed"
    if row["review_decision"] == "rejected":
        return "licence_rejected"
    if row["review_decision"] is None:
        return "no_licence_review"
    return "licence_unverified"


async def _refresh_manifest(db, client, collection: str) -> dict:
    from sqlalchemy import text

    versions = set()
    offset = None
    while True:
        points, offset = await asyncio.to_thread(
            client.scroll,
            collection,
            limit=8192,
            offset=offset,
            with_payload=["document_version_id"],
            with_vectors=False,
        )
        versions.update(str(p.payload.get("document_version_id")) for p in points)
        if offset is None:
            break
    point_count = await asyncio.to_thread(
        lambda: client.count(collection_name=collection, exact=True).count
    )
    document_count = (
        await db.execute(
            text(
                "SELECT count(DISTINCT d.id) FROM kb_documents d "
                "WHERE d.status='active' AND d.index_eligibility='eligible' "
                "AND d.technical_review_status<>'fail' "
                "AND d.current_version_id::text = ANY(:versions)"
            ),
            {"versions": sorted(versions)},
        )
    ).scalar_one()
    await db.execute(
        text(
            "UPDATE index_manifests SET document_count=:docs, point_count=:points, "
            "updated_at=now() WHERE collection=:c"
        ),
        {"docs": document_count, "points": point_count, "c": collection},
    )
    await db.commit()
    return {"documents": document_count, "points": point_count}


async def isolate(apply: bool, confirm: bool) -> int:
    from sqlalchemy import text

    from app.config import settings
    from app.db import SessionLocal, init_db
    from app.retrieval.vector_store import (
        count_version_points,
        delete_version_points,
        get_client,
    )

    if apply and not confirm:
        print("--apply requires --confirm", file=sys.stderr)
        return 2
    await init_db()
    client = get_client()
    collection = settings.qdrant_collection

    async with SessionLocal() as db:
        rows = [dict(r._mapping) for r in (await db.execute(text(TARGETS_SQL))).all()]
        if not rows:
            print("nothing to isolate")
            return 0
        for row in rows:
            row["points"] = await asyncio.to_thread(
                count_version_points, client, row["current_version_id"]
            )

        by_reason: dict[str, int] = {}
        for row in rows:
            by_reason[isolation_reason(row)] = by_reason.get(isolation_reason(row), 0) + 1
        print(f"documents to isolate: {len(rows)}")
        print(f"  reasons: {by_reason}")
        print(f"  child chunks: {sum(r['child_chunks'] for r in rows)}")
        print(f"  qdrant points: {sum(r['points'] for r in rows)}")
        if not apply:
            return 0

        stamp = datetime.now(UTC)
        for row in rows:
            reason = isolation_reason(row)
            await db.execute(
                text(
                    "UPDATE kb_documents SET index_eligibility=:e, "
                    "metadata = coalesce(metadata,'{}'::jsonb) || cast(:flag AS jsonb), "
                    "updated_at=now() WHERE id=:id"
                ),
                {
                    "e": target_eligibility(row),
                    "flag": json.dumps(
                        {
                            "licence_isolation": {
                                "at": stamp.isoformat().replace("+00:00", "Z"),
                                "reason": reason,
                                "review_scope": row["review_scope"],
                                "review_decision": row["review_decision"],
                                "points_removed": row["points"],
                                "policy": "licence basis not approved; data kept, index removed",
                            }
                        },
                        ensure_ascii=False,
                    ),
                    "id": row["id"],
                },
            )
        await db.commit()

        removed = 0
        for row in rows:
            if row["points"]:
                await asyncio.to_thread(
                    delete_version_points, client, row["current_version_id"]
                )
                removed += row["points"]

        manifest = await _refresh_manifest(db, client, collection)
        report = {
            "at": stamp.isoformat().replace("+00:00", "Z"),
            "collection": collection,
            "policy": (
                "remove from the formal index, keep rows/files/evidence; "
                "restore after an explicit licence decision"
            ),
            "totals": {
                "documents": len(rows),
                "points_removed": removed,
                "by_reason": by_reason,
            },
            "manifest_after": manifest,
            "documents": [
                {
                    "document_id": str(r["id"]),
                    "title": r["title"],
                    "source_org": r["source_org"],
                    "version_id": str(r["current_version_id"]),
                    "child_chunks": r["child_chunks"],
                    "points_removed": r["points"],
                    "eligibility_after": target_eligibility(r),
                    "reason": isolation_reason(r),
                    "review_scope": r["review_scope"],
                }
                for r in rows
            ],
        }
        out = ROOT / "data" / "reports" / f"licence_isolation_{stamp:%Y%m%dT%H%M%SZ}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"removed {removed} points; manifest {manifest}")
        print(f"wrote {out}")
        print(f"restore: .venv/bin/python scripts/isolate_licence_pending.py --restore --manifest {out}")
    return 0


async def restore(manifest_path: Path, apply: bool, confirm: bool) -> int:
    import uuid

    from reindex_collection import _draft
    from sqlalchemy import select, text

    from app.config import settings
    from app.db import SessionLocal, init_db
    from app.ingestion.embedder import get_embedder
    from app.models import KbChunk, KbDocument
    from app.retrieval.bm25 import BM25SparseEncoder
    from app.retrieval.vector_store import (
        count_version_points,
        get_client,
        upsert_chunks,
    )

    if apply and not confirm:
        print("--restore --apply requires --confirm", file=sys.stderr)
        return 2
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    client = get_client()
    collection = settings.qdrant_collection
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
    restored = blocked = 0
    started = time.perf_counter()
    await init_db()
    async with SessionLocal() as db:
        for item in data["documents"]:
            decision = (
                await db.execute(
                    text(
                        "SELECT r.decision FROM kb_documents d "
                        "JOIN licence_reviews r ON r.id=d.licence_review_id WHERE d.id=:id"
                    ),
                    {"id": item["document_id"]},
                )
            ).scalar_one_or_none()
            if decision != "approved":
                blocked += 1
                print(f"skip (review={decision}): {item['title'][:60]}")
                continue
            doc = await db.get(KbDocument, uuid.UUID(item["document_id"]))
            if doc is None:
                blocked += 1
                continue
            chunks = (
                (
                    await db.execute(
                        select(KbChunk)
                        .where(
                            KbChunk.document_version_id == item["version_id"],
                            KbChunk.chunk_role == "child",
                        )
                        .order_by(KbChunk.ordinal)
                    )
                )
                .scalars()
                .all()
            )
            if not chunks:
                blocked += 1
                continue
            if not apply:
                print(f"would restore {len(chunks)} chunks: {item['title'][:60]}")
                continue
            doc_id = uuid.UUID(item["document_id"])
            version_id = uuid.UUID(item["version_id"])
            dense = await asyncio.to_thread(
                embedder.embed_documents, [c.content for c in chunks]
            )
            sparse = [bm25.document_vector(c.content) for c in chunks]
            await asyncio.to_thread(
                upsert_chunks,
                client,
                [_draft(c) for c in chunks],
                dense,
                sparse,
                doc_id,
                version_id,
                doc.category,
                list(doc.species or []),
            )
            indexed = await asyncio.to_thread(count_version_points, client, version_id)
            if indexed != len(chunks):
                raise RuntimeError(f"restore mismatch {version_id}: {indexed} != {len(chunks)}")
            await db.execute(
                text(
                    "UPDATE kb_documents SET index_eligibility='eligible', "
                    "metadata = metadata || cast(:flag AS jsonb), updated_at=now() WHERE id=:id"
                ),
                {
                    "id": item["document_id"],
                    "flag": json.dumps(
                        {"licence_isolation_restored_at": datetime.now(UTC).isoformat()}
                    ),
                },
            )
            await db.commit()
            restored += 1
    if apply:
        async with SessionLocal() as db:
            print(await _refresh_manifest(db, client, collection))
    print(f"restored {restored}, skipped {blocked}, {time.perf_counter() - started:.0f}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()
    if args.restore:
        if not args.manifest:
            parser.error("--restore needs --manifest <isolation report>")
        return asyncio.run(restore(args.manifest, args.apply, args.confirm))
    return asyncio.run(isolate(args.apply, args.confirm))


if __name__ == "__main__":
    raise SystemExit(main())