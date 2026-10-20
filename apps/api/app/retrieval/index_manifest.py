"""Read/write the physical index manifest used for reproducible retrieval."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IndexManifest


async def get_manifest(db: AsyncSession, collection: str) -> IndexManifest | None:
    return (
        await db.execute(select(IndexManifest).where(IndexManifest.collection == collection))
    ).scalar_one_or_none()


async def check_manifest(
    db: AsyncSession,
    *,
    collection: str,
    embedding_model: str,
    vector_size: int,
    chunk_config_hash: str | None = None,
) -> dict:
    manifest = await get_manifest(db, collection)
    if manifest is None:
        return {
            "collection": collection,
            "present": False,
            "ok": False,
            "warnings": ["index_manifest_missing"],
        }
    warnings: list[str] = []
    if manifest.embedding_model != embedding_model:
        warnings.append("manifest_embedding_model_mismatch")
    if manifest.vector_size != vector_size:
        warnings.append("manifest_vector_size_mismatch")
    if chunk_config_hash and manifest.chunk_config_hash != chunk_config_hash:
        warnings.append("manifest_chunk_config_mismatch")
    return {
        "collection": collection,
        "present": True,
        "ok": not warnings,
        "status": manifest.status,
        "embedding_model": manifest.embedding_model,
        "vector_size": manifest.vector_size,
        "chunk_config_hash": manifest.chunk_config_hash,
        "document_count": manifest.document_count,
        "point_count": manifest.point_count,
        "warnings": warnings,
    }


async def upsert_manifest(
    db: AsyncSession,
    *,
    collection: str,
    embedding_model: str,
    vector_size: int,
    chunk_config_hash: str,
    status: str,
    document_count: int,
    point_count: int,
) -> IndexManifest:
    manifest = await get_manifest(db, collection)
    if manifest is None:
        manifest = IndexManifest(
            collection=collection,
            embedding_model=embedding_model,
            vector_size=vector_size,
            chunk_config_hash=chunk_config_hash,
        )
        db.add(manifest)
    manifest.embedding_model = embedding_model
    manifest.vector_size = vector_size
    manifest.chunk_config_hash = chunk_config_hash
    manifest.status = status
    manifest.document_count = document_count
    manifest.point_count = point_count
    manifest.updated_at = datetime.now(UTC)
    await db.flush()
    return manifest
