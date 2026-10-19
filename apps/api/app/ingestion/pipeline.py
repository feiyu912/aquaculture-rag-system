from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.graph.service import link_chunks, load_graph
from app.ingestion.chunker import build_chunks
from app.ingestion.context import build_context_text
from app.ingestion.embedder import get_embedder
from app.ingestion.parser import ParsedDocument, PyMuPDFParser
from app.models import KbChunk, KbDocument, KbDocumentVersion, KbIngestJob
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.vector_store import (
    count_version_points,
    delete_version_points,
    ensure_collection,
    get_client,
    upsert_chunks,
)

PIPELINE_VERSION = "v1"


def _now() -> datetime:
    return datetime.now(UTC)


def _chunk_config_hash() -> str:
    raw = (
        f"{settings.parent_target_chars}:{settings.child_target_chars}:"
        f"{settings.child_overlap_chars}:{settings.embedding_model}:"
        f"{settings.enable_contextual_retrieval}:{PIPELINE_VERSION}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


async def _set_stage(db: AsyncSession, job: KbIngestJob, stage: str, progress: int) -> None:
    job.current_stage = stage
    job.progress = progress
    job.status = "running"
    await db.commit()


async def ingest_version(ctx: dict, version_id: str) -> dict:
    version_uuid = uuid.UUID(version_id)
    started = time.perf_counter()
    parser = PyMuPDFParser()

    async with SessionLocal() as db:
        version = await db.get(KbDocumentVersion, version_uuid)
        if version is None:
            return {"status": "missing", "version_id": version_id}
        doc = await db.get(KbDocument, version.document_id)
        job = (
            await db.execute(
                select(KbIngestJob).where(KbIngestJob.document_version_id == version_uuid)
            )
        ).scalar_one_or_none()
        if doc is None or job is None:
            return {"status": "missing_relations", "version_id": version_id}
        if doc.status == "deleted":
            job.status = "cancelled"
            job.current_stage = "cancelled"
            job.error_code = "document_deleted"
            job.error_message = "文档已删除，任务取消"
            job.finished_at = _now()
            await db.commit()
            return {"status": "document_deleted", "version_id": version_id}
        if version.status == "ready" and doc.current_version_id == version.id:
            job.status = "succeeded"
            job.progress = 100
            job.current_stage = "done"
            await db.commit()
            return {"status": "already_active", "version_id": version_id}

        job.attempts = int(ctx.get("job_try", 1)) if ctx else 1
        job.status = "running"
        job.started_at = job.started_at or _now()
        job.error_code = None
        job.error_message = None
        version.status = "processing"
        version.error_code = None
        version.error_message = None
        await db.commit()

        try:
            await _set_stage(db, job, "parse", 10)
            parsed: ParsedDocument = await asyncio.to_thread(parser.parse, _path(version.file_path))
            version.page_count = parsed.page_count
            version.parser_name = parsed.parser_name
            version.parser_version = parsed.parser_version
            await db.commit()

            await _set_stage(db, job, "chunk", 30)
            drafts = build_chunks(
                parsed,
                version.id,
                parent_target=settings.parent_target_chars,
                child_target=settings.child_target_chars,
                overlap=settings.child_overlap_chars,
            )
            children = [chunk for chunk in drafts if chunk.role == "child"]
            if not children:
                raise ValueError("No chunks produced from PDF")
            context_by_id = {
                draft.id: build_context_text(
                    title=doc.title,
                    heading_path=draft.heading_path,
                    species=doc.species,
                    content=draft.content,
                    block_type=draft.block_type,
                )
                for draft in drafts
            }

            await db.execute(delete(KbChunk).where(KbChunk.document_version_id == version.id))
            for draft in drafts:
                db.add(
                    KbChunk(
                        id=draft.id,
                        document_version_id=version.id,
                        parent_id=draft.parent_id,
                        chunk_role=draft.role,
                        ordinal=draft.ordinal,
                        content=draft.content,
                        context_text=context_by_id[draft.id],
                        content_hash=hashlib.sha256(draft.content.encode()).hexdigest(),
                        heading_path=draft.heading_path,
                        block_type=draft.block_type,
                        page_from=draft.page_from,
                        page_to=draft.page_to,
                        token_count=draft.token_count,
                        locations=draft.locations,
                    )
                )
            await db.commit()

            # Entity mentions are document metadata: build them independently
            # of the graph-expansion switch so ablations can use the same links.
            graph = await load_graph(db)
            if graph.entities:
                await link_chunks(
                    db,
                    [(chunk.id, chunk.content) for chunk in children],
                    graph,
                )
                await db.commit()

            await _set_stage(db, job, "embed", 50)
            embedder = get_embedder(settings.embedding_model, settings.qdrant_vector_size)
            bm25 = BM25SparseEncoder(
                k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len
            )
            if settings.enable_contextual_retrieval:
                index_texts = [context_by_id[chunk.id] for chunk in children]
            else:
                index_texts = [chunk.content for chunk in children]
            dense_vectors = await asyncio.to_thread(embedder.embed_documents, index_texts)
            sparse_vectors = [bm25.document_vector(text) for text in index_texts]

            await _set_stage(db, job, "upsert", 75)
            client = get_client()
            try:
                await asyncio.to_thread(ensure_collection, client)
                await asyncio.to_thread(delete_version_points, client, version.id)
                await asyncio.to_thread(
                    upsert_chunks,
                    client,
                    children,
                    dense_vectors,
                    sparse_vectors,
                    version.document_id,
                    version.id,
                    doc.category,
                    doc.species,
                )
                indexed = await asyncio.to_thread(count_version_points, client, version.id)
            finally:
                client.close()
            if indexed != len(children):
                raise RuntimeError(f"Qdrant point count mismatch: {indexed} != {len(children)}")

            await _set_stage(db, job, "activate", 90)
            await _activate(db, doc.id, version.id)

            job.status = "succeeded"
            job.progress = 100
            job.current_stage = "done"
            job.finished_at = _now()
            job.metrics = {
                "page_count": parsed.page_count,
                "chunks": len(drafts),
                "children": len(children),
                "dense_dim": settings.qdrant_vector_size,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            }
            version.embedding_model = settings.embedding_model
            version.chunk_config_hash = _chunk_config_hash()
            await db.commit()
            return {
                "status": "ok",
                "version_id": version_id,
                "chunks": len(drafts),
                "children": len(children),
            }
        except Exception as exc:
            await db.rollback()
            await _mark_failed(db, version_uuid, exc)
            raise


def _path(raw: str) -> str:
    from pathlib import Path

    return str(Path(raw))


async def _activate(db: AsyncSession, document_id: uuid.UUID, version_id: uuid.UUID) -> None:
    doc = (
        await db.execute(select(KbDocument).where(KbDocument.id == document_id).with_for_update())
    ).scalar_one()
    if doc.status == "deleted":
        raise ValueError("Document was deleted during ingestion")

    version = await db.get(KbDocumentVersion, version_id)
    if version is None or version.document_id != document_id:
        raise ValueError("Version does not belong to document")

    # A retried older job must not overwrite a newer active version.
    current = (
        await db.get(KbDocumentVersion, doc.current_version_id) if doc.current_version_id else None
    )
    if current is not None and current.version_no > version.version_no:
        version.status = "archived"
        version.archived_at = _now()
        await db.flush()
        return

    version.status = "ready"
    version.activated_at = _now()
    doc.current_version_id = version.id
    doc.status = "active"
    await db.execute(
        update(KbDocumentVersion)
        .where(
            KbDocumentVersion.document_id == document_id,
            KbDocumentVersion.id != version_id,
            KbDocumentVersion.status == "ready",
        )
        .values(status="archived", archived_at=_now())
    )
    await db.flush()


async def _mark_failed(db: AsyncSession, version_id: uuid.UUID, exc: Exception) -> None:
    version = await db.get(KbDocumentVersion, version_id)
    job = (
        await db.execute(select(KbIngestJob).where(KbIngestJob.document_version_id == version_id))
    ).scalar_one_or_none()
    if version:
        version.status = "failed"
        version.error_code = exc.__class__.__name__
        version.error_message = str(exc)[:1000]
    if job:
        job.status = "failed"
        job.error_code = exc.__class__.__name__
        job.error_message = str(exc)[:1000]
        job.finished_at = _now()
    await db.commit()
