"""Rebuild Qdrant BM25 sparse vectors from current chunk text.

Dense vectors are deliberately untouched.  Use this when the tokenizer/custom
term list changed after a collection was indexed; otherwise BM25 silently misses
terms that exist in the source text (observed for ``溶氧量`` on R061).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from qdrant_client import QdrantClient, models

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings
from app.db import SessionLocal
from app.models import KbChunk
from app.retrieval.bm25 import BM25SparseEncoder


async def run(apply: bool, collection: str, limit: int) -> int:
    encoder = BM25SparseEncoder(
        k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len
    )
    client = QdrantClient(url=settings.qdrant_url)
    offset = None
    scanned = changed = missing = 0
    updates: list[models.PointVectors] = []
    async with SessionLocal() as db:
        while True:
            points, offset = client.scroll(
                collection_name=collection,
                limit=128,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            for point in points:
                scanned += 1
                payload = point.payload or {}
                chunk_id = payload.get("chunk_id")
                if not chunk_id:
                    missing += 1
                    continue
                chunk = await db.get(KbChunk, uuid.UUID(str(chunk_id)))
                if chunk is None:
                    missing += 1
                    continue
                expected = encoder.document_vector(chunk.content)
                vectors = point.vector or {}
                current = vectors.get("bm25") if isinstance(vectors, dict) else None
                if current is None or list(current.indices) != list(expected.indices):
                    changed += 1
                    if apply:
                        updates.append(models.PointVectors(id=point.id, vector={"bm25": expected}))
                        if len(updates) >= 64:
                            client.update_vectors(collection_name=collection, points=updates)
                            updates.clear()
                if limit and scanned >= limit:
                    break
            if offset is None or (limit and scanned >= limit):
                break
    if apply and updates:
        client.update_vectors(collection_name=collection, points=updates)
    print(
        f"collection={collection} scanned={scanned} changed={changed} "
        f"missing={missing} applied={apply}"
    )
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default=settings.qdrant_collection)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.apply, args.collection, args.limit))


if __name__ == "__main__":
    main()
