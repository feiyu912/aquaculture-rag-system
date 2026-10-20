"""Soft-delete vector cleanup and manifest maintenance.

The database rows and original PDFs are intentionally retained.  Only derived
Qdrant points whose document version belongs to a soft-deleted document are
removed, and only after a retention window: a mistaken delete can be undone by
restoring the row before the grace period ends, without re-ingesting the PDF.
Both the worker task and the CLI use this module so the two paths cannot drift.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.ingestion.pipeline import chunk_config_hash
from app.models import KbDocument, KbDocumentVersion
from app.retrieval.bm25 import bm25_config_hash
from app.retrieval.index_manifest import get_manifest, upsert_manifest
from app.retrieval.vector_store import count_version_points, delete_version_points, get_client

logger = logging.getLogger(__name__)


def retention_cutoff(days: int, *, now: datetime | None = None) -> datetime:
    """Documents deleted more recently than this cutoff are kept intact."""
    return (now or datetime.now(UTC)) - timedelta(days=max(int(days), 0))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _delete_marker(deleted_at: datetime | None, updated_at: datetime | None) -> datetime | None:
    """Prefer the explicit delete timestamp; legacy rows fall back to updated_at."""
    return _as_utc(deleted_at) or _as_utc(updated_at)


def is_expired(deleted_at: datetime | None, updated_at: datetime | None, cutoff: datetime) -> bool:
    marker = _delete_marker(deleted_at, updated_at)
    # A row with no timestamp at all cannot prove it is recent; treat it as
    # expired so a broken migration cannot pin derived vectors forever.
    return marker is None or marker < cutoff


async def refresh_manifest(client) -> dict:
    """Recompute active point/document counts after a cleanup.

    A Qdrant deletion that leaves the SQL manifest unchanged makes the next
    startup think the collection is complete.  Refresh only the counts that the
    cleanup can change; embedding model and chunk/BM25 config remain untouched.
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
            bm25_config_hash=manifest.bm25_config_hash or bm25_config_hash(),
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


async def purge_deleted_vectors(
    *, apply: bool = False, retention_days: int | None = None
) -> dict:
    """Remove points for expired soft-deleted documents; dry-run by default.

    ``retention_days=0`` purges immediately (explicit opt-in for tests/ops).
    """
    days = settings.soft_delete_retention_days if retention_days is None else retention_days
    cutoff = retention_cutoff(days)
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    KbDocumentVersion.id,
                    KbDocument.id,
                    KbDocument.title,
                    KbDocument.deleted_at,
                    KbDocument.updated_at,
                )
                .join(KbDocument, KbDocument.id == KbDocumentVersion.document_id)
                .where(KbDocument.status == "deleted")
                .order_by(KbDocument.created_at, KbDocumentVersion.version_no)
            )
        ).all()

    expired = [row for row in rows if is_expired(row.deleted_at, row.updated_at, cutoff)]
    retained = [row for row in rows if not is_expired(row.deleted_at, row.updated_at, cutoff)]

    client = get_client()
    versions: list[dict] = []
    manifest: dict = {"refreshed": False}
    try:
        for version_id, document_id, title, _deleted_at, _updated_at in expired:
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
        "retention_days": days,
        "retention_cutoff": cutoff.isoformat(),
        "deleted_documents": len({item["document_id"] for item in versions}),
        "versions_with_points": len(versions),
        "points_to_remove": sum(item["points"] for item in versions),
        "retained_documents": len({str(row[1]) for row in retained}),
        "retained_versions": len(retained),
        "versions": versions,
    }
    logger.info(
        "soft-delete vector cleanup dry_run=%s retention_days=%s versions=%s points=%s retained=%s",
        not apply,
        days,
        result["versions_with_points"],
        result["points_to_remove"],
        result["retained_versions"],
    )
    return result