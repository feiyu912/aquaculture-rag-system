"""Build a new Qdrant collection from PostgreSQL chunks.

The source of truth is PostgreSQL: documents, versions, parent/child chunks.
Qdrant is rebuilt from those rows, then a manifest is written only after the
point count matches. The active collection is never modified unless the caller
explicitly passes ``--recreate`` and the target name.

Examples:
  uv run python ../../scripts/reindex_collection.py \
      --collection kb_chunks_bge_m3_v1 \
      --embedding-model BAAI/bge-m3

  uv run python ../../scripts/reindex_collection.py \
      --collection kb_chunks_bge_m3_ctx_v1 \
      --embedding-model BAAI/bge-m3 --contextual
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings
from app.db import SessionLocal, engine, init_db
from app.ingestion.chunker import ChunkDraft
from app.ingestion.embedder import get_embedder
from app.ingestion.pipeline import chunk_config_hash
from app.models import KbChunk, KbDocument, KbDocumentVersion
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.bm25 import bm25_config_hash
from app.retrieval.index_manifest import upsert_manifest
from app.retrieval.vector_store import (
    count_version_points,
    ensure_collection,
    get_client,
    upsert_chunks,
)


def _draft(row: KbChunk) -> ChunkDraft:
    return ChunkDraft(
        id=row.id,
        parent_id=row.parent_id,
        role=row.chunk_role,
        ordinal=row.ordinal,
        content=row.content,
        heading_path=list(row.heading_path or []),
        block_type=row.block_type,
        page_from=row.page_from,
        page_to=row.page_to,
        token_count=row.token_count,
        locations=list(row.locations or []),
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default="kb_chunks_bge_m3_v1")
    parser.add_argument("--embedding-model", default=settings.embedding_model)
    parser.add_argument("--recreate", action="store_true", help="delete target collection first")
    parser.add_argument("--contextual", action="store_true", help="index context_text")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    active_collection = settings.qdrant_collection
    if args.collection == active_collection:
        raise SystemExit("target collection must differ from the currently configured collection")
    settings.qdrant_collection = args.collection
    settings.embedding_model = args.embedding_model
    settings.embedding_batch_size = args.batch_size
    settings.enable_contextual_retrieval = args.contextual

    if args.embedding_model.startswith("hashing"):
        raise SystemExit("reindex_collection.py requires a real model, not hashing-dev")
    if args.collection == "kb_chunks_dev_v1" and args.recreate:
        raise SystemExit(
            "refusing to recreate the development collection without a separate target"
        )

    await init_db()
    client = get_client()
    started = time.perf_counter()
    try:
        exists = client.collection_exists(args.collection)
        if exists and not args.recreate:
            raise SystemExit(
                f"collection {args.collection!r} already exists; use --recreate or a new name"
            )
        if exists:
            client.delete_collection(args.collection)
        ensure_collection(client)

        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(KbDocument, KbDocumentVersion, KbChunk)
                    .join(KbDocumentVersion, KbDocumentVersion.document_id == KbDocument.id)
                    .join(KbChunk, KbChunk.document_version_id == KbDocumentVersion.id)
                    .where(
                        KbDocument.status == "active",
                        KbDocumentVersion.status.in_(["ready", "archived"]),
                        KbChunk.chunk_role == "child",
                    )
                    .order_by(KbDocument.id, KbDocumentVersion.version_no, KbChunk.ordinal)
                )
            ).all()

        by_version: dict[tuple, list[KbChunk]] = defaultdict(list)
        doc_by_version: dict[tuple, tuple[KbDocument, KbDocumentVersion]] = {}
        for doc, version, chunk in rows:
            key = (doc.id, version.id)
            by_version[key].append(chunk)
            doc_by_version[key] = (doc, version)
        if not by_version:
            raise SystemExit("no active child chunks found")

        embedder = get_embedder(
            args.embedding_model,
            settings.qdrant_vector_size,
            settings.embedding_device,
            settings.embedding_use_fp16,
            settings.embedding_batch_size,
            settings.embedding_max_length,
        )
        bm25 = BM25SparseEncoder(
            k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len
        )
        document_ids: set = set()
        points = 0
        for (document_id, version_id), chunks in by_version.items():
            doc, version = doc_by_version[(document_id, version_id)]
            drafts = [_draft(chunk) for chunk in chunks]
            dense_texts = [
                (chunk.context_text if args.contextual and chunk.context_text else chunk.content)
                for chunk in chunks
            ]
            # Keep sparse retrieval on raw text when context is enabled; see
            # app.ingestion.pipeline.chunk_config_hash for the matching scheme.
            sparse_texts = [chunk.content for chunk in chunks]
            dense = await asyncio.to_thread(embedder.embed_documents, dense_texts)
            sparse = [bm25.document_vector(text) for text in sparse_texts]
            await asyncio.to_thread(
                upsert_chunks,
                client,
                drafts,
                dense,
                sparse,
                document_id,
                version_id,
                doc.category,
                doc.species,
            )
            indexed = await asyncio.to_thread(count_version_points, client, version_id)
            if indexed != len(drafts):
                raise RuntimeError(
                    f"point count mismatch for {version_id}: {indexed} != {len(drafts)}"
                )
            points += indexed
            document_ids.add(str(document_id))
            print(f"indexed {doc.title} v{version.version_no}: {indexed} points", flush=True)

        async with SessionLocal() as db:
            await upsert_manifest(
                db,
                collection=args.collection,
                embedding_model=args.embedding_model,
                vector_size=settings.qdrant_vector_size,
                chunk_config_hash=chunk_config_hash(),
                bm25_config_hash=bm25_config_hash(),
                status="active",
                document_count=len(document_ids),
                point_count=points,
            )
            await db.commit()

        print(
            json.dumps(
                {
                    "collection": args.collection,
                    "embedding_model": args.embedding_model,
                    "contextual": args.contextual,
                    "documents": len(document_ids),
                    "versions": len(by_version),
                    "points": points,
                    "elapsed_s": round(time.perf_counter() - started, 1),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception:
        # Never leave a half-built target that could be mistaken for complete.
        if client.collection_exists(args.collection):
            client.delete_collection(args.collection)
        raise
    finally:
        client.close()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
