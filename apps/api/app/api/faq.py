"""FAQ review and (only after review) indexing.

The review endpoint is the *single* place where ``review_status`` can become
``verified``.  It refuses to verify an entry that has no traceable, still-active
supporting document, which is what stops model-generated text from being
promoted into the evidence pool.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.faq.review import ReviewError, reject_faq, verify_faq
from app.models import FaqEntry
from app.trust import VERIFIED

router = APIRouter(prefix="/api/faq", tags=["faq"])


class FaqOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    species: list[str] = Field(default_factory=list)
    topic: str | None = None
    source_dataset: str
    source_authority: str
    review_status: str
    usage_scope: str
    evidence_status: str
    quality_flags: list = Field(default_factory=list)
    supporting_count: int = 0
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    indexed_at: datetime | None = None


class FaqDetail(FaqOut):
    supporting: list = Field(default_factory=list)
    review_notes: str | None = None
    original_answer: str | None = None


class ReviewRequest(BaseModel):
    action: str = Field(pattern="^(verify|reject)$")
    reviewer: str = Field(min_length=1, max_length=64)
    answer: str | None = None
    notes: str | None = None


def _out(entry: FaqEntry) -> FaqOut:
    return FaqOut(
        id=entry.id,
        question=entry.question,
        answer=entry.answer,
        species=list(entry.species or []),
        topic=entry.topic,
        source_dataset=entry.source_dataset,
        source_authority=entry.source_authority,
        review_status=entry.review_status,
        usage_scope=entry.usage_scope,
        evidence_status=entry.evidence_status,
        quality_flags=list(entry.quality_flags or []),
        supporting_count=len(entry.supporting or []),
        reviewer=entry.reviewer,
        reviewed_at=entry.reviewed_at,
        indexed_at=entry.indexed_at,
    )


@router.get("", response_model=list[FaqOut])
async def list_faq(
    review_status: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[FaqOut]:
    statement = select(FaqEntry).order_by(FaqEntry.created_at.desc())
    if review_status:
        statement = statement.where(FaqEntry.review_status == review_status)
    if topic:
        statement = statement.where(FaqEntry.topic == topic)
    rows = (await db.execute(statement.limit(limit).offset(offset))).scalars().all()
    return [_out(row) for row in rows]


@router.get("/stats")
async def faq_stats(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        await db.execute(
            select(FaqEntry.review_status, FaqEntry.evidence_status, func.count())
            .group_by(FaqEntry.review_status, FaqEntry.evidence_status)
        )
    ).all()
    return {
        "by_status": [
            {"review_status": status, "evidence_status": evidence, "count": count}
            for status, evidence, count in rows
        ],
        "indexed": sum(
            count for status, _, count in rows if status == VERIFIED
        ),
    }


@router.get("/{faq_id}", response_model=FaqDetail)
async def get_faq(faq_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> FaqDetail:
    entry = await db.get(FaqEntry, faq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    return FaqDetail(
        **_out(entry).model_dump(),
        supporting=list(entry.supporting or []),
        review_notes=entry.review_notes,
        original_answer=entry.original_answer,
    )


async def _active_supporting_versions(db: AsyncSession, entry: FaqEntry) -> list[str]:
    """Return supporting version ids that still belong to an active document."""
    version_ids = [
        str(item.get("version_id"))
        for item in (entry.supporting or [])
        if isinstance(item, dict) and item.get("version_id")
    ]
    if not version_ids:
        return []
    rows = (
        await db.execute(
            select(KbDocumentVersion.id)
            .join(KbDocument, KbDocument.id == KbDocumentVersion.document_id)
            .where(
                KbDocumentVersion.id.in_([uuid.UUID(v) for v in version_ids]),
                KbDocument.status == "active",
                KbDocument.verification_status == VERIFIED,
                KbDocument.current_version_id == KbDocumentVersion.id,
            )
        )
    ).scalars().all()
    return [str(row) for row in rows]


@router.post("/{faq_id}/review", response_model=FaqOut)
async def review_faq(
    faq_id: uuid.UUID, payload: ReviewRequest, db: AsyncSession = Depends(get_db)
) -> FaqOut:
    entry = await db.get(FaqEntry, faq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    try:
        if payload.action == "reject":
            await reject_faq(db, entry, reviewer=payload.reviewer, notes=payload.notes)
        else:
            await verify_faq(
                db,
                entry,
                reviewer=payload.reviewer,
                answer=payload.answer,
                notes=payload.notes,
            )
    except ReviewError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return _out(entry)
