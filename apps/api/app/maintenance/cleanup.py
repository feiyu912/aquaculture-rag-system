"""Soft-delete vector cleanup and manifest maintenance.

The database rows and original PDFs are intentionally retained.  Only derived
Qdrant points whose document version belongs to a soft-deleted document are
removed.  Both the worker task and the CLI use this module so the two paths
cannot drift.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.ingestion.pipeline import chunk_config_hash
from app.models import KbDocument, KbDocumentVersion
from app.retrieval.index_manifest import get_manifest, upsert_manifest
from app.retrieval.vector_store import count_version_points, delete_version_points, get_client

logger = logging.getLogger(__name__)


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
        point_count = sum(count_version_points(client, version_id) for version_id in version_ids)
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


async def purge_deleted_vectors(*, apply: bool = False) -> dict:
    """Remove points for soft-deleted documents; dry-run by default."""
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
    manifest: dict = {"refreshed": False}
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
            manifest = await refresh_manifest(client)
    finally:
        client.close()

    result = {
        "dry_run": not apply,
        "manifest": manifest,
        "collection": settings.qdrant_collection,
        "deleted_documents": len({item["document_id"] for item in versions}),
        "versions_with_points": len(versions),
        "points_to_remove": sum(item["points"] for item in versions),
        "versions": versions,
    }
    logger.info(
        "soft-delete vector cleanup dry_run=%s versions=%s points=%s",
        not apply,
        result["versions_with_points"],
        result["points_to_remove"],
    )
    return result
