"""Dry-run/apply removal of Qdrant vectors for soft-deleted documents.

The database rows and original PDFs are deliberately kept: this script only
removes derived Qdrant points that no active version can reference. Run without
``--apply`` first; the default is read-only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings
from app.db import SessionLocal
from app.ingestion.pipeline import chunk_config_hash
from app.models import KbDocument, KbDocumentVersion
from app.retrieval.index_manifest import get_manifest, upsert_manifest
from app.retrieval.vector_store import (
    count_version_points,
    delete_version_points,
    get_client,
)


async def refresh_manifest(client) -> dict:
    """Recompute active point/document counts after a cleanup.

    A Qdrant deletion that leaves the SQL manifest unchanged makes the next
    startup think the collection is complete.  Refresh only the counts that the
    cleanup can change; embedding model and chunk config remain untouched.
    """
    async with SessionLocal() as db:
        manifest = await get_manifest(db, settings.qdrant_collection)
        if manifest is None:
            return {"refreshed": False, "error": "manifest_missing"}
        rows = (
            await db.execute(
                select(KbDocument.id, KbDocumentVersion.id)
                .join(KbDocumentVersion, KbDocumentVersion.document_id == KbDocument.id)
                .where(
                    KbDocument.status == "active",
                    KbDocumentVersion.status.in_(["ready", "archived"]),
                )
            )
        ).all()
        document_ids = {str(document_id) for document_id, _ in rows}
        version_ids = [version_id for _, version_id in rows]
        point_count = sum(
            count_version_points(client, version_id) for version_id in version_ids
        )
        await upsert_manifest(
            db,
            collection=settings.qdrant_collection,
            embedding_model=manifest.embedding_model,
            vector_size=manifest.vector_size,
            chunk_config_hash=manifest.chunk_config_hash or chunk_config_hash(),
            status=manifest.status,
            document_count=len(document_ids),
            point_count=point_count,
        )
        await db.commit()
    return {
        "refreshed": True,
        "document_count": len(document_ids),
        "point_count": point_count,
        "collection": settings.qdrant_collection,
    }


async def collect(apply: bool) -> dict:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(KbDocumentVersion.id, KbDocument.id, KbDocument.title)
                .join(KbDocument, KbDocument.id == KbDocumentVersion.document_id)
                .where(KbDocument.status == "deleted")
                .order_by(KbDocument.created_at, KbDocumentVersion.version_no)
            )
        ).all()

    client = get_client()
    versions: list[dict] = []
    try:
        for version_id, document_id, title in rows:
            points = count_version_points(client, version_id)
            if points:
                versions.append(
                    {
                        "title": title,
                        "document_id": str(document_id),
                        "version_id": str(version_id),
                        "points": points,
                    }
                )
        if apply:
            for item in versions:
                delete_version_points(client, uuid.UUID(item["version_id"]))
        manifest = await refresh_manifest(client) if apply else {"refreshed": False}
    finally:
        client.close()

    return {
        "dry_run": not apply,
        "manifest": manifest,
        "collection": settings.qdrant_collection,
        "deleted_documents": len({item["document_id"] for item in versions}),
        "versions_with_points": len(versions),
        "points_to_remove": sum(item["points"] for item in versions),
        "versions": versions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="actually delete orphan points"
    )
    args = parser.parse_args()
    result = asyncio.run(collect(args.apply))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
