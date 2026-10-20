"""Check that the active PostgreSQL version pointers and Qdrant index agree.

This is a read-only diagnostic. It does not repair data and it does not prove
retrieval quality; it catches the common failure mode where a collection is
reused after changing the embedding model or chunking configuration.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings
from app.db import SessionLocal
from app.models import KbDocument, KbDocumentVersion
from app.retrieval.vector_store import get_client


async def collect() -> dict:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(KbDocument, KbDocumentVersion)
                .join(KbDocumentVersion, KbDocumentVersion.id == KbDocument.current_version_id)
                .where(KbDocument.status == "active")
                .order_by(KbDocument.created_at)
            )
        ).all()

    versions = [
        {
            "title": doc.title,
            "version_id": str(version.id),
            "version_no": version.version_no,
            "embedding_model": version.embedding_model,
            "chunk_config_hash": version.chunk_config_hash,
        }
        for doc, version in rows
    ]
    models = sorted({item["embedding_model"] for item in versions if item["embedding_model"]})
    hashes = sorted({item["chunk_config_hash"] for item in versions if item["chunk_config_hash"]})
    missing_metadata = [
        item for item in versions if not item["embedding_model"] or not item["chunk_config_hash"]
    ]

    client = get_client()
    try:
        info = client.get_collection(settings.qdrant_collection)
        vectors = info.config.params.vectors
        if isinstance(vectors, dict):
            dense = vectors.get("dense")
            vector_size = getattr(dense, "size", None)
        else:
            vector_size = getattr(vectors, "size", None)
        points = client.count(collection_name=settings.qdrant_collection, exact=True).count
    finally:
        client.close()

    warnings: list[str] = []
    if len(models) > 1:
        warnings.append("active versions use more than one embedding model")
    if len(hashes) > 1:
        warnings.append("active versions use more than one chunk configuration")
    if missing_metadata:
        warnings.append("some active versions have empty embedding/chunk metadata")
    if models and settings.embedding_model not in models:
        warnings.append("configured embedding model is not represented in active versions")
    if vector_size is not None and vector_size != settings.qdrant_vector_size:
        warnings.append("Qdrant dense size differs from QDRANT_VECTOR_SIZE")

    return {
        "collection": settings.qdrant_collection,
        "configured_embedding_model": settings.embedding_model,
        "configured_vector_size": settings.qdrant_vector_size,
        "collection_vector_size": vector_size,
        "collection_points": int(points),
        "active_versions": len(versions),
        "active_embedding_models": models,
        "active_chunk_config_hashes": hashes,
        "missing_metadata": missing_metadata,
        "warnings": warnings,
        "ok": not warnings,
        "versions": versions,
    }


def main() -> int:
    result = asyncio.run(collect())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
