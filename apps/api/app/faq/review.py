"""Review workflow shared by the API endpoint and the seeding script.

Keeping this out of the router means there is exactly one implementation of
"may this FAQ become verified?", and the script cannot accidentally use a
weaker path than the human-facing endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.faq.normalize import content_hash
from app.models import FaqEntry, KbDocument, KbDocumentVersion
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.faq_store import delete_faq, faq_text, upsert_faq
from app.retrieval.vector_store import ensure_collection, get_client
from app.trust import REJECTED, VERIFIED


class ReviewError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


async def active_supporting_versions(db: AsyncSession, entry: FaqEntry) -> list[str]:
    version_ids = [
        str(item.get("version_id"))
        for item in (entry.supporting or [])
        if isinstance(item, dict) and item.get("version_id")
    ]
    if not version_ids:
        return []
    parsed = []
    for value in version_ids:
        try:
            parsed.append(uuid.UUID(value))
        except (ValueError, TypeError):
            continue
    if not parsed:
        return []
    rows = (
        await db.execute(
            select(KbDocumentVersion.id)
            .join(KbDocument, KbDocument.id == KbDocumentVersion.document_id)
            .where(
                KbDocumentVersion.id.in_(parsed),
                KbDocument.status == "active",
                KbDocument.verification_status == VERIFIED,
                KbDocument.current_version_id == KbDocumentVersion.id,
            )
        )
    ).scalars().all()
    return [str(row) for row in rows]


async def verify_faq(
    db: AsyncSession,
    entry: FaqEntry,
    *,
    reviewer: str,
    answer: str | None = None,
    notes: str | None = None,
) -> FaqEntry:
    if entry.usage_scope == "eval":
        raise ReviewError(409, "评测专用条目（usage_scope=eval）不得进入知识库")
    if entry.review_status == VERIFIED:
        raise ReviewError(409, "该条目已通过复核")

    active = await active_supporting_versions(db, entry)
    if not active:
        raise ReviewError(
            422, "缺少仍处于 active 状态的支撑文献，无法核验。请先补充或更新支撑证据。"
        )
    if entry.evidence_status != "supported":
        raise ReviewError(422, f"证据链状态为 {entry.evidence_status}，不足以核验")

    if answer and answer.strip() and answer.strip() != entry.answer:
        entry.original_answer = entry.original_answer or entry.answer
        entry.answer = answer.strip()
        entry.content_hash = content_hash(entry.question, entry.answer)

    entry.review_status = VERIFIED
    entry.reviewer = reviewer
    entry.reviewed_at = datetime.now(UTC)
    entry.review_notes = notes
    await db.commit()

    from app.ingestion.embedder import get_embedder

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
    text = faq_text(entry.question, entry.answer)
    payload = {
        "question": entry.question,
        "answer": entry.answer,
        "species": list(entry.species or []),
        "category": entry.topic or "FAQ",
        "source_authority": entry.source_authority,
        "publisher": entry.source_dataset,
        "source_url": entry.original_source_url,
        "supporting_document_ids": [
            item.get("document_id")
            for item in (entry.supporting or [])
            if isinstance(item, dict)
        ],
        "supporting_version_ids": active,
        "verification_status": VERIFIED,
    }
    client = get_client()
    try:
        ensure_collection(client)
        upsert_faq(client, entry.id, payload, embedder.embed_query(text), bm25.document_vector(text))
    finally:
        client.close()

    entry.indexed_at = datetime.now(UTC)
    entry.index_collection = settings.qdrant_collection
    await db.commit()
    return entry


async def reject_faq(
    db: AsyncSession, entry: FaqEntry, *, reviewer: str, notes: str | None = None
) -> FaqEntry:
    entry.review_status = REJECTED
    entry.reviewer = reviewer
    entry.reviewed_at = datetime.now(UTC)
    entry.review_notes = notes
    client = get_client()
    try:
        if entry.indexed_at is not None:
            delete_faq(client, entry.id)
    finally:
        client.close()
    entry.indexed_at = None
    await db.commit()
    return entry