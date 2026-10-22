"""Read-only data-management API.

This router is deliberately separate from ``/api/documents``:

* the legacy list endpoint keeps returning a plain array (older clients keep
  working);
* this module provides server-side pagination, stable ordering, combinable
  filters, accurate totals and the review/provenance detail the management UI
  needs.

Nothing here changes document state.  Promotion, deletion, retry and FAQ
review stay on their existing endpoints, with their existing guards.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _doc_out, _version_out
from app.collection.registry import load_registry
from app.config import settings
from app.db import get_db
from app.management.catalog import (
    DOCUMENT_TYPE_AUTHORITIES,
    DOCUMENT_TYPE_LABELS,
    classify_document_type,
    describe_review_flag,
    document_type_label,
    is_failed_document,
    source_identity,
    summarize_chunks,
    summarize_documents,
    summarize_versions,
)
from app.media import normalize_media_type, public_locations
from app.models import (
    DataRun,
    FaqEntry,
    KbChunk,
    KbDocument,
    KbDocumentVersion,
    KbIngestJob,
)
from app.retrieval.faq_store import faq_filter
from app.retrieval.vector_store import get_client
from app.runtime_settings import LLM_MODEL_KEY, env_llm_model, get_setting, set_setting
from app.schemas import DocumentOut, LlmModelUpdate, VersionOut
from app.species import normalize_species_list

router = APIRouter(prefix="/api/manage", tags=["manage"])

SORT_OPTIONS = {
    "created_desc": "最新入库",
    "created_asc": "最早入库",
    "updated_desc": "最近更新",
    "title_asc": "标题 A→Z",
    "title_desc": "标题 Z→A",
    "year_desc": "出版年份新→旧",
}

_DOC_STATUSES = {"active", "staging", "failed", "deleted", "processing"}


class ManagedDocument(DocumentOut):
    updated_at: datetime
    language: str | None = None
    license: str | None = None
    document_type: str = "other"
    document_type_label: str = "其他/未分类"
    storage_policy: str = "metadata_only"
    storage_policy_label: str = "仅元数据"
    source_id: str | None = None
    current_version_status: str | None = None
    published: bool = False
    retrievable: bool = False
    parent_chunks: int = 0
    child_chunks: int = 0


class DocumentPage(BaseModel):
    items: list[ManagedDocument]
    total: int
    page: int
    page_size: int
    pages: int
    has_next: bool
    has_prev: bool
    sort: str
    applied_filters: dict = Field(default_factory=dict)


class ManagedVersion(VersionOut):
    parser_name: str | None = None
    parser_version: str | None = None
    file_size: int = 0
    error_code: str | None = None
    parent_chunks: int = 0
    child_chunks: int = 0
    job_status: str | None = None
    job_id: uuid.UUID | None = None


class JobSummary(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    document_title: str
    version_no: int
    job_type: str
    status: str
    progress: int
    current_stage: str
    attempts: int
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class JobPage(BaseModel):
    items: list[JobSummary]
    total: int
    limit: int
    offset: int


class ReviewFlag(BaseModel):
    code: str
    label: str


class ChunkPreview(BaseModel):
    id: uuid.UUID
    chunk_role: str
    ordinal: int
    page_from: int
    page_to: int
    heading_path: list[str] = Field(default_factory=list)
    content: str
    truncated: bool = False
    locations: list = Field(default_factory=list)


class ManagedDocumentDetail(ManagedDocument):
    versions: list[ManagedVersion] = Field(default_factory=list)
    jobs: list[JobSummary] = Field(default_factory=list)
    chunks_preview: list[ChunkPreview] = Field(default_factory=list)
    review_flag_details: list[ReviewFlag] = Field(default_factory=list)
    source: dict = Field(default_factory=dict)
    storage: dict = Field(default_factory=dict)
    review: dict = Field(default_factory=dict)


class ChunkPage(BaseModel):
    items: list[ChunkPreview]
    total: int
    limit: int
    offset: int


class FaqSupport(BaseModel):
    document_id: str | None = None
    version_id: str | None = None
    chunk_id: str | None = None
    title: str | None = None
    version_no: int | None = None
    page: int | None = None
    quote: str | None = None
    score: float | None = None
    source_type: str | None = None
    source_url: str | None = None
    available: bool = False
    unavailable_reason: str | None = None


class ManagedFaq(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    species: list[str] = Field(default_factory=list)
    topic: str | None = None
    region: str | None = None
    review_status: str
    usage_scope: str
    evidence_status: str
    quality_flags: list = Field(default_factory=list)
    source_dataset: str = ""
    source_authority: str = "unknown"
    original_source_url: str | None = None
    source_license: str | None = None
    supporting_count: int = 0
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    indexed_at: datetime | None = None
    indexed: bool = False
    review_provenance: str = "unrecorded"
    review_provenance_label: str = "未记录核验来源"
    domain_review_status: str = "not_recorded"
    supporting: list[FaqSupport] = Field(default_factory=list)


class FaqPage(BaseModel):
    items: list[ManagedFaq]
    total: int
    limit: int
    offset: int


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _meta(doc: KbDocument) -> dict:
    return doc.doc_metadata or {}


def _storage_policy(source_type: str) -> tuple[str, str]:
    if source_type == "html":
        return "html_snapshot", "HTML 快照；不伪造 PDF 页码"
    if source_type == "pdf":
        return "local_pdf", "原始 PDF 留存于服务端；按版本定位"
    return "metadata_only", "仅元数据"


def _to_managed(
    doc: KbDocument,
    version: KbDocumentVersion | None,
    *,
    parent: int = 0,
    child: int = 0,
    status_override: str | None = None,
) -> ManagedDocument:
    base = _doc_out(doc, version)
    payload = base.model_dump()
    if status_override:
        payload["status"] = status_override
    meta = _meta(doc)
    source_type = normalize_media_type(doc.source_type)
    dtype = classify_document_type(doc.authority_level, meta)
    published = bool(
        doc.status == "active"
        and doc.verification_status == "verified"
        and doc.current_version_id is not None
    )
    retrievable = published and version is not None and version.status == "ready"
    storage_policy, storage_label = _storage_policy(source_type)
    return ManagedDocument(
        **payload,
        updated_at=doc.updated_at,
        language=meta.get("language"),
        license=meta.get("license"),
        document_type=dtype,
        document_type_label=document_type_label(dtype),
        storage_policy=storage_policy,
        storage_policy_label=storage_label,
        source_id=meta.get("source_id"),
        current_version_status=version.status if version else None,
        published=published,
        retrievable=retrievable,
        parent_chunks=parent,
        child_chunks=child,
    )


def _sort_clause(sort: str):
    if sort not in SORT_OPTIONS:
        sort = "created_desc"
    if sort == "created_asc":
        return (KbDocument.created_at.asc(), KbDocument.id.asc())
    if sort == "updated_desc":
        return (KbDocument.updated_at.desc(), KbDocument.id.desc())
    if sort == "title_asc":
        return (KbDocument.title.asc(), KbDocument.id.asc())
    if sort == "title_desc":
        return (KbDocument.title.desc(), KbDocument.id.desc())
    if sort == "year_desc":
        return (KbDocument.publish_year.desc().nullslast(), KbDocument.id.desc())
    return (KbDocument.created_at.desc(), KbDocument.id.desc())


def _published_condition():
    return (
        (KbDocument.status == "active")
        & KbDocument.current_version_id.is_not(None)
        & (KbDocument.verification_status == "verified")
    )


def _draft_condition():
    """A draft can be declared in three places; any one of them wins."""
    return or_(
        KbDocument.authority_level == "standard_draft",
        func.coalesce(KbDocument.doc_metadata["document_status"].astext, "") == "draft",
        func.coalesce(KbDocument.doc_metadata["doc_type"].astext, "") == "standard_draft",
    )


def _document_type_condition(values: list[str]):
    known = set()
    for authorities in DOCUMENT_TYPE_AUTHORITIES.values():
        known.update(authorities)
    clauses = []
    for value in values:
        authorities = DOCUMENT_TYPE_AUTHORITIES.get(value)
        if value == "standard":
            # A binding authority with a draft marker is still a draft.
            clauses.append(
                and_(KbDocument.authority_level.in_(sorted(authorities or ())), not_(_draft_condition()))
            )
        elif value == "standard_draft":
            clauses.append(_draft_condition())
        elif authorities:
            clauses.append(
                and_(KbDocument.authority_level.in_(sorted(authorities)), not_(_draft_condition()))
            )
        elif value == "other":
            clauses.append(
                and_(
                    or_(
                        KbDocument.authority_level.is_(None),
                        KbDocument.authority_level.notin_(sorted(known)),
                    ),
                    not_(_draft_condition()),
                )
            )
    return or_(*clauses) if clauses else None


def _latest_version_status_subquery():
    return (
        select(KbDocumentVersion.status)
        .where(KbDocumentVersion.document_id == KbDocument.id)
        .order_by(KbDocumentVersion.version_no.desc())
        .limit(1)
        .correlate(KbDocument)
        .scalar_subquery()
    )


def _failed_condition():
    """SQL mirror of ``catalog.is_failed_document``."""
    return and_(
        KbDocument.status != "deleted",
        or_(
            KbDocument.status == "failed",
            and_(
                KbDocument.current_version_id.is_(None),
                _latest_version_status_subquery() == "failed",
            ),
        ),
    )


def _not_failed_condition():
    """SQL complement of ``_failed_condition`` that is NULL-safe.

    ``NOT (subquery = 'failed')`` evaluates to NULL when a document has no
    versions at all, which would silently drop never-ingested staging rows.
    """
    return and_(
        KbDocument.status != "failed",
        or_(
            KbDocument.current_version_id.is_not(None),
            func.coalesce(_latest_version_status_subquery(), "") != "failed",
        ),
    )


def _display_status(doc: KbDocument, latest_status: str | None) -> str:
    if is_failed_document(
        {
            "status": doc.status,
            "current_version_id": doc.current_version_id,
            "latest_version_status": latest_status,
        }
    ):
        return "failed"
    return doc.status


def _build_filters(
    *,
    q: str | None,
    statuses: list[str],
    published: str | None,
    technical_review: list[str],
    domain_review: list[str],
    document_type: list[str],
    source_type: list[str],
    authority_level: list[str],
    language: list[str],
    species: list[str],
    category: list[str],
    license_values: list[str],
    source_id: str | None,
):
    clauses = []
    if statuses:
        lifecycle = [value for value in statuses if value != "failed"]
        normal = (
            and_(KbDocument.status.in_(lifecycle), _not_failed_condition())
            if lifecycle
            else None
        )
        if "failed" in statuses:
            clauses.append(or_(*([normal, _failed_condition()] if normal is not None else [_failed_condition()])))
        else:
            clauses.append(normal)
    else:
        clauses.append(KbDocument.status != "deleted")
    if published == "true":
        clauses.append(_published_condition())
    elif published == "false":
        clauses.append(~_published_condition())
    if technical_review:
        clauses.append(KbDocument.technical_review_status.in_(technical_review))
    if domain_review:
        clauses.append(KbDocument.domain_review_status.in_(domain_review))
    dtype_condition = _document_type_condition(document_type)
    if dtype_condition is not None:
        clauses.append(dtype_condition)
    if source_type:
        source_values = set(source_type)
        if "html" in source_values:
            source_values.add("web")
        clauses.append(KbDocument.source_type.in_(sorted(source_values)))
    if authority_level:
        clauses.append(KbDocument.authority_level.in_(authority_level))
    for value in language:
        if value == "未标注":
            clauses.append(
                or_(
                    KbDocument.doc_metadata["language"].astext.is_(None),
                    KbDocument.doc_metadata["language"].astext == "",
                )
            )
        else:
            clauses.append(KbDocument.doc_metadata["language"].astext == value)
    for value in species:
        clauses.append(KbDocument.species.any(value))
    if category:
        clauses.append(KbDocument.category.in_(category))
    for value in license_values:
        if value == "未声明":
            clauses.append(
                or_(
                    KbDocument.doc_metadata["license"].astext.is_(None),
                    KbDocument.doc_metadata["license"].astext == "",
                )
            )
        else:
            clauses.append(KbDocument.doc_metadata["license"].astext == value)
    if source_id:
        clauses.append(KbDocument.doc_metadata["source_id"].astext == source_id)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        clauses.append(
            or_(
                KbDocument.title.ilike(needle),
                KbDocument.category.ilike(needle),
                KbDocument.source_org.ilike(needle),
                KbDocument.source_url.ilike(needle),
                KbDocument.doc_metadata["source_id"].astext.ilike(needle),
            )
        )
    return clauses


async def _chunk_counts(
    db: AsyncSession, version_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    if not version_ids:
        return {}
    rows = (
        await db.execute(
            select(KbChunk.document_version_id, KbChunk.chunk_role, func.count())
            .where(KbChunk.document_version_id.in_(version_ids))
            .group_by(KbChunk.document_version_id, KbChunk.chunk_role)
        )
    ).all()
    result: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
    for version_id, role, count in rows:
        result[version_id][role] = int(count)
    return result


@router.get("/documents", response_model=DocumentPage)
async def list_documents_page(
    q: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, description="逗号分隔：active,staging,failed,deleted"),
    published: str | None = Query(default=None, pattern="^(true|false)$"),
    technical_review: str | None = Query(default=None),
    domain_review: str | None = Query(default=None),
    document_type: str | None = Query(default=None),
    source_type: str | None = Query(default=None, alias="source_type"),
    authority_level: str | None = Query(default=None),
    language: str | None = Query(default=None),
    species: str | None = Query(default=None),
    category: str | None = Query(default=None),
    license: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    sort: str = Query(default="created_desc"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DocumentPage:
    statuses = _split_csv(status)
    invalid = set(statuses) - _DOC_STATUSES
    if invalid:
        raise HTTPException(status_code=400, detail=f"不支持的状态：{', '.join(sorted(invalid))}")
    clauses = _build_filters(
        q=q,
        statuses=statuses,
        published=published,
        technical_review=_split_csv(technical_review),
        domain_review=_split_csv(domain_review),
        document_type=_split_csv(document_type),
        source_type=_split_csv(source_type),
        authority_level=_split_csv(authority_level),
        language=_split_csv(language),
        species=_split_csv(species),
        category=_split_csv(category),
        license_values=_split_csv(license),
        source_id=source_id,
    )
    total = int(
        (await db.execute(select(func.count()).select_from(KbDocument).where(*clauses))).scalar_one()
    )
    docs = (
        (
            await db.execute(
                select(KbDocument)
                .where(*clauses)
                .order_by(*_sort_clause(sort))
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    current_ids = [doc.current_version_id for doc in docs if doc.current_version_id]
    versions = (
        (
            await db.execute(
                select(KbDocumentVersion).where(KbDocumentVersion.id.in_(current_ids))
            )
        )
        .scalars()
        .all()
        if current_ids
        else []
    )
    version_by_id = {version.id: version for version in versions}
    latest_rows = (
        await db.execute(
            select(
                KbDocumentVersion.document_id,
                KbDocumentVersion.status,
            )
            .where(KbDocumentVersion.document_id.in_([doc.id for doc in docs]))
            .order_by(KbDocumentVersion.document_id, KbDocumentVersion.version_no.desc())
        )
    ).all()
    latest_status_by_doc: dict[uuid.UUID, str] = {}
    for document_id, version_status in latest_rows:
        latest_status_by_doc.setdefault(document_id, version_status)
    counts = await _chunk_counts(db, current_ids)
    items = []
    for doc in docs:
        version = version_by_id.get(doc.current_version_id) if doc.current_version_id else None
        doc_counts = counts.get(doc.current_version_id, {}) if doc.current_version_id else {}
        items.append(
            _to_managed(
                doc,
                version,
                parent=doc_counts.get("parent", 0),
                child=doc_counts.get("child", 0),
                status_override=_display_status(doc, latest_status_by_doc.get(doc.id)),
            )
        )
    pages = (total + limit - 1) // limit if total else 0
    applied = {
        "q": q,
        "status": statuses or ["active", "staging", "failed"],
        "published": published,
        "technical_review": _split_csv(technical_review),
        "domain_review": _split_csv(domain_review),
        "document_type": _split_csv(document_type),
        "source_type": _split_csv(source_type),
        "authority_level": _split_csv(authority_level),
        "language": _split_csv(language),
        "species": _split_csv(species),
        "category": _split_csv(category),
        "license": _split_csv(license),
        "source_id": source_id,
    }
    return DocumentPage(
        items=items,
        total=total,
        page=(offset // limit) + 1,
        page_size=limit,
        pages=pages,
        has_next=offset + len(items) < total,
        has_prev=offset > 0,
        sort=sort if sort in SORT_OPTIONS else "created_desc",
        applied_filters=applied,
    )


async def _load_all_documents(db: AsyncSession) -> list[dict]:
    docs = (
        (
            await db.execute(
                select(
                    KbDocument.id,
                    KbDocument.status,
                    KbDocument.verification_status,
                    KbDocument.current_version_id,
                    KbDocument.source_url,
                    KbDocument.authority_level,
                    KbDocument.technical_review_status,
                    KbDocument.domain_review_status,
                    KbDocument.doc_metadata,
                )
            )
        )
        .mappings()
        .all()
    )
    versions = (
        (
            await db.execute(
                select(
                    KbDocumentVersion.id,
                    KbDocumentVersion.document_id,
                    KbDocumentVersion.status,
                    KbDocumentVersion.content_hash,
                    KbDocumentVersion.version_no,
                ).order_by(KbDocumentVersion.document_id, KbDocumentVersion.version_no.desc())
            )
        )
        .mappings()
        .all()
    )
    latest_status: dict[uuid.UUID, str] = {}
    status_by_version: dict[uuid.UUID, str] = {}
    hash_by_version: dict[uuid.UUID, str] = {}
    for version in versions:
        latest_status.setdefault(version["document_id"], version["status"])
        status_by_version[version["id"]] = version["status"]
        hash_by_version[version["id"]] = version["content_hash"]
    rows = []
    for doc in docs:
        meta = doc["doc_metadata"] or {}
        url = doc["source_url"] or meta.get("final_url") or meta.get("requested_url")
        dtype = classify_document_type(doc["authority_level"], meta)
        content_hash = (
            hash_by_version.get(doc["current_version_id"])
            if doc["current_version_id"]
            else None
        )
        rows.append(
            {
                "id": str(doc["id"]),
                "status": doc["status"],
                "verification_status": doc["verification_status"],
                "current_version_id": doc["current_version_id"],
                "source_url": url,
                "content_hash": content_hash,
                "current_version_status": (
                    status_by_version.get(doc["current_version_id"])
                    if doc["current_version_id"]
                    else None
                ),
                "document_type": dtype,
                "technical_review_status": doc["technical_review_status"],
                "domain_review_status": doc["domain_review_status"],
                "latest_version_status": latest_status.get(doc["id"]),
                "source_key": source_identity(
                    source_url=url,
                    content_hash=content_hash,
                    document_id=str(doc["id"]),
                ),
            }
        )
    return rows, versions


async def _faq_index_points() -> tuple[int | None, str | None]:
    client = get_client()
    try:
        result = await asyncio.to_thread(
            lambda: client.count(
                collection_name=settings.qdrant_collection,
                count_filter=faq_filter(),
                exact=True,
            )
        )
        return int(result.count), None
    except Exception as exc:  # Qdrant is optional for a stats call
        return None, str(exc)[:200]
    finally:
        client.close()


async def _source_registry_stats() -> dict:
    registry_path = settings.data_path.parent / "sources" / "registry.yaml"
    if not registry_path.exists():
        registry_path = settings.data_path / "sources" / "registry.yaml"
    registered = 0
    try:
        if registry_path.exists():
            registered = len(load_registry(registry_path))
    except Exception:
        registered = 0
    return {"registered": registered}


@router.get("/stats")
async def catalog_stats(db: AsyncSession = Depends(get_db)) -> dict:
    rows, versions = await _load_all_documents(db)
    doc_stats = summarize_documents(rows)
    version_stats = summarize_versions(list(versions))

    version_to_doc = {version["id"]: version["document_id"] for version in versions}
    doc_status = {row["id"]: row["status"] for row in rows}
    live_version_count = sum(
        1
        for version in versions
        if doc_status.get(str(version_to_doc.get(version["id"]))) != "deleted"
    )
    version_stats["live_total"] = live_version_count
    version_stats["deleted_total"] = len(versions) - live_version_count
    current_by_doc = {
        str(row["id"]): row["current_version_id"] for row in rows
    }
    chunk_groups = (
        await db.execute(
            select(KbChunk.document_version_id, KbChunk.chunk_role, func.count()).group_by(
                KbChunk.document_version_id, KbChunk.chunk_role
            )
        )
    ).all()
    all_chunks = []
    active_chunks = []
    staging_chunks = []
    deleted_chunks = []
    for version_id, role, count in chunk_groups:
        group = {"chunk_role": role, "count": count}
        all_chunks.append(group)
        doc_id = version_to_doc.get(version_id)
        if doc_id is None:
            continue
        status = doc_status.get(str(doc_id))
        is_current = str(current_by_doc.get(str(doc_id))) == str(version_id)
        if is_current and status == "active":
            active_chunks.append(group)
        elif is_current and status == "staging":
            staging_chunks.append(group)
        elif status == "deleted":
            deleted_chunks.append(group)

    faq_rows = (
        await db.execute(
            select(
                FaqEntry.review_status,
                FaqEntry.evidence_status,
                FaqEntry.usage_scope,
                FaqEntry.indexed_at,
            )
        )
    ).mappings().all()
    faq_by_status = Counter(str(row["review_status"]) for row in faq_rows)
    faq_by_scope = Counter(str(row["usage_scope"]) for row in faq_rows)
    faq_by_evidence = Counter(str(row["evidence_status"]) for row in faq_rows)
    indexed_rows = [
        row
        for row in faq_rows
        if row["review_status"] == "verified" and row["indexed_at"] is not None
    ]
    faq_points, faq_points_error = await _faq_index_points()

    latest_runs = (
        (
            await db.execute(
                select(DataRun)
                .where(DataRun.kind.in_(["crawl", "faq_import"]))
                .order_by(DataRun.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    run_stats: dict[str, dict] = {}
    for run in latest_runs:
        run_stats.setdefault(run.kind, run.stats or {})

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "documents": doc_stats,
        "versions": version_stats,
        "chunks": {
            "all_versions": summarize_chunks(all_chunks),
            "current_active": summarize_chunks(active_chunks),
            "current_staging": summarize_chunks(staging_chunks),
            "deleted_versions": summarize_chunks(deleted_chunks),
        },
        "faq": {
            "total": len(faq_rows),
            "pending": faq_by_status.get("pending", 0),
            "verified": faq_by_status.get("verified", 0),
            "rejected": faq_by_status.get("rejected", 0),
            "by_status": dict(sorted(faq_by_status.items())),
            "by_scope": dict(sorted(faq_by_scope.items())),
            "by_evidence_status": dict(sorted(faq_by_evidence.items())),
            "verified_indexed": len(indexed_rows),
            # ``index_points`` is read from Qdrant, not inferred from the DB;
            # the two can legitimately differ after a failed cleanup.
            "index_points": faq_points,
            "index_points_error": faq_points_error,
        },
        "sources": {
            **(await _source_registry_stats()),
            "latest_crawl": run_stats.get("crawl", {}),
            "latest_faq_import": run_stats.get("faq_import", {}),
        },
    }


@router.get("/facets")
async def catalog_facets(
    include_deleted: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        await db.execute(
            select(
                KbDocument.id,
                KbDocument.status,
                KbDocument.current_version_id,
                KbDocument.category,
                KbDocument.species,
                KbDocument.source_type,
                KbDocument.authority_level,
                KbDocument.technical_review_status,
                KbDocument.domain_review_status,
                KbDocument.doc_metadata,
            )
        )
    ).mappings().all()
    latest_rows = (
        await db.execute(
            select(KbDocumentVersion.document_id, KbDocumentVersion.status).order_by(
                KbDocumentVersion.document_id, KbDocumentVersion.version_no.desc()
            )
        )
    ).all()
    latest_status_by_doc: dict[uuid.UUID, str] = {}
    for document_id, version_status in latest_rows:
        latest_status_by_doc.setdefault(document_id, version_status)
    live_rows = [row for row in rows if row["status"] != "deleted"]
    # ``include_deleted`` only adds the deleted status bucket.  Trust/type
    # facets always describe live material, otherwise a deleted test row would
    # inflate the counts shown next to an active-only list.
    rows = rows if include_deleted else live_rows

    def counter(values) -> list[dict]:
        counts = Counter(str(value) for value in values if value)
        return [
            {"value": value, "count": count}
            for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    species = Counter()
    languages = Counter()
    licenses = Counter()
    doc_types = Counter()
    for row in live_rows:
        species.update(normalize_species_list(row["species"]))
        meta = row["doc_metadata"] or {}
        languages[str(meta.get("language") or "未标注")] += 1
        licenses[str(meta.get("license") or "未声明")] += 1
        doc_types[classify_document_type(row["authority_level"], meta)] += 1

    status_values = []
    for row in rows:
        latest = latest_status_by_doc.get(row["id"])
        status_values.append(
            "failed"
            if is_failed_document(
                {
                    "status": row["status"],
                    "current_version_id": row["current_version_id"],
                    "latest_version_status": latest,
                }
            )
            else row["status"]
        )

    return {
        "status": counter(status_values),
        "category": counter(row["category"] for row in live_rows),
        "species": [
            {"value": value, "count": count}
            for value, count in sorted(species.items(), key=lambda item: (-item[1], item[0]))
        ],
        "source_type": counter(
            normalize_media_type(row["source_type"]) for row in live_rows
        ),
        "authority_level": counter(row["authority_level"] for row in live_rows),
        "technical_review_status": counter(row["technical_review_status"] for row in live_rows),
        "domain_review_status": counter(row["domain_review_status"] for row in live_rows),
        "language": [
            {"value": value, "count": count}
            for value, count in sorted(languages.items(), key=lambda item: (-item[1], item[0]))
        ],
        "license": [
            {"value": value, "count": count}
            for value, count in sorted(licenses.items(), key=lambda item: (-item[1], item[0]))
        ],
        "document_type": [
            {
                "value": value,
                "label": DOCUMENT_TYPE_LABELS.get(value, value),
                "count": count,
            }
            for value, count in sorted(doc_types.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def _review_flag_list(doc: KbDocument) -> list[ReviewFlag]:
    return [
        ReviewFlag(code=str(code), label=describe_review_flag(str(code)))
        for code in (doc.review_flags or [])
    ]


def _chunk_preview(
    chunk: KbChunk, limit: int = 1200, media_type: str | None = None
) -> ChunkPreview:
    content = chunk.content or ""
    return ChunkPreview(
        id=chunk.id,
        chunk_role=chunk.chunk_role,
        ordinal=chunk.ordinal,
        page_from=chunk.page_from,
        page_to=chunk.page_to,
        heading_path=list(chunk.heading_path or []),
        content=content[:limit],
        truncated=len(content) > limit,
        locations=public_locations(list(chunk.locations or []), media_type or "pdf"),
    )


async def _latest_version(db: AsyncSession, doc: KbDocument) -> KbDocumentVersion | None:
    if doc.current_version_id:
        current = await db.get(KbDocumentVersion, doc.current_version_id)
        if current is not None:
            return current
    return (
        await db.execute(
            select(KbDocumentVersion)
            .where(KbDocumentVersion.document_id == doc.id)
            .order_by(KbDocumentVersion.version_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get("/documents/{document_id}", response_model=ManagedDocumentDetail)
async def document_detail(
    document_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ManagedDocumentDetail:
    doc = await db.get(KbDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    versions = (
        (
            await db.execute(
                select(KbDocumentVersion)
                .where(KbDocumentVersion.document_id == document_id)
                .order_by(KbDocumentVersion.version_no.desc())
            )
        )
        .scalars()
        .all()
    )
    version_ids = [version.id for version in versions]
    counts = await _chunk_counts(db, version_ids)
    jobs = (
        (
            await db.execute(
                select(KbIngestJob)
                .where(KbIngestJob.document_version_id.in_(version_ids))
                .order_by(KbIngestJob.created_at.desc())
            )
        )
        .scalars()
        .all()
        if version_ids
        else []
    )
    job_by_version: dict[uuid.UUID, KbIngestJob] = {}
    for job in jobs:
        job_by_version.setdefault(job.document_version_id, job)
    current = next((v for v in versions if v.id == doc.current_version_id), None)
    if current is None:
        current = versions[0] if versions else None
    current_counts = counts.get(current.id, {}) if current else {}
    base = _to_managed(
        doc,
        current,
        parent=current_counts.get("parent", 0),
        child=current_counts.get("child", 0),
        status_override=_display_status(
            doc, versions[0].status if versions else None
        ),
    )
    preview_version = current
    preview: list[ChunkPreview] = []
    if preview_version is not None:
        chunks = (
            (
                await db.execute(
                    select(KbChunk)
                    .where(KbChunk.document_version_id == preview_version.id)
                    .order_by(KbChunk.chunk_role.desc(), KbChunk.ordinal.asc())
                    .limit(6)
                )
            )
            .scalars()
            .all()
        )
        preview = [
            _chunk_preview(chunk, 600, normalize_media_type(doc.source_type))
            for chunk in chunks
        ]

    managed_versions = []
    for version in versions:
        vc = counts.get(version.id, {})
        job = job_by_version.get(version.id)
        managed_versions.append(
            ManagedVersion(
                **_version_out(version).model_dump(),
                parser_name=version.parser_name,
                parser_version=version.parser_version,
                file_size=version.file_size,
                error_code=version.error_code,
                parent_chunks=vc.get("parent", 0),
                child_chunks=vc.get("child", 0),
                job_status=job.status if job else None,
                job_id=job.id if job else None,
            )
        )
    job_items = []
    for job in jobs:
        version = next((item for item in versions if item.id == job.document_version_id), None)
        job_items.append(
            JobSummary(
                id=job.id,
                document_id=doc.id,
                document_version_id=job.document_version_id,
                document_title=doc.title,
                version_no=version.version_no if version else 0,
                job_type=job.job_type,
                status=job.status,
                progress=job.progress,
                current_stage=job.current_stage,
                attempts=job.attempts,
                error_code=job.error_code,
                error_message=job.error_message,
                started_at=job.started_at,
                finished_at=job.finished_at,
                created_at=job.created_at,
            )
        )

    meta = _meta(doc)
    source_type = normalize_media_type(doc.source_type)
    source = {
        "source_type": source_type,
        "source_id": meta.get("source_id"),
        "source_org": doc.source_org,
        "source_url": doc.source_url,
        "requested_url": meta.get("requested_url"),
        "final_url": meta.get("final_url"),
        "publish_year": doc.publish_year,
        "effective_date": doc.effective_date,
        "fetched_at": doc.fetched_at,
        "language": meta.get("language"),
        "license": meta.get("license"),
        "doc_type": meta.get("doc_type"),
        "document_status": meta.get("document_status"),
        "region": meta.get("region") or doc.region,
        "species": normalize_species_list(doc.species),
        "authority_level": doc.authority_level,
        "verification_status": doc.verification_status,
        "robots": meta.get("robots"),
    }
    storage_policy, storage_label = _storage_policy(source_type)
    storage = {
        "policy": storage_policy,
        "label": storage_label,
        "original_file_available": bool(
            current is not None and current.file_path and Path(current.file_path).exists()
        ),
        "current_version_id": str(current.id) if current else None,
        "index_collection": settings.qdrant_collection,
    }
    review = {
        "technical_review_status": doc.technical_review_status,
        "domain_review_status": doc.domain_review_status,
        "verification_status": doc.verification_status,
        "reviewed_at": doc.reviewed_at,
        "technical_note": "技术检查覆盖来源可追溯、解析完整性、页码/定位可用性；自动化检查不等同于领域认可。",
        "domain_note": "领域审核只能由水产领域人员记录；pending 表示尚未确认技术结论适用性。",
        "review_flags": _review_flag_list(doc),
    }
    return ManagedDocumentDetail(
        **base.model_dump(),
        versions=managed_versions,
        jobs=job_items,
        chunks_preview=preview,
        review_flag_details=_review_flag_list(doc),
        source=source,
        storage=storage,
        review=review,
    )


@router.get("/documents/{document_id}/chunks", response_model=ChunkPage)
async def document_chunks(
    document_id: uuid.UUID,
    version_id: uuid.UUID | None = Query(default=None),
    role: str | None = Query(default=None, pattern="^(parent|child)$"),
    page: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ChunkPage:
    doc = await db.get(KbDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if version_id is not None:
        version = await db.get(KbDocumentVersion, version_id)
        if version is None or version.document_id != document_id:
            raise HTTPException(status_code=404, detail="版本不存在")
    else:
        version = await _latest_version(db, doc)
        if version is None:
            raise HTTPException(status_code=404, detail="文档没有可用版本")
    clauses = [KbChunk.document_version_id == version.id]
    if role:
        clauses.append(KbChunk.chunk_role == role)
    if page is not None:
        clauses.append((KbChunk.page_from <= page) & (KbChunk.page_to >= page))
    if q:
        clauses.append(KbChunk.content.ilike(f"%{q.strip()}%"))
    total = int(
        (await db.execute(select(func.count()).select_from(KbChunk).where(*clauses))).scalar_one()
    )
    chunks = (
        (
            await db.execute(
                select(KbChunk)
                .where(*clauses)
                .order_by(KbChunk.chunk_role.desc(), KbChunk.ordinal.asc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return ChunkPage(
        items=[
            _chunk_preview(chunk, media_type=normalize_media_type(doc.source_type))
            for chunk in chunks
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs", response_model=JobPage)
async def list_jobs(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    document_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> JobPage:
    clauses = []
    statuses = _split_csv(status)
    if statuses:
        clauses.append(KbIngestJob.status.in_(statuses))
    if kind:
        clauses.append(KbIngestJob.job_type == kind)
    if document_id is not None:
        clauses.append(KbDocument.id == document_id)
    base = (
        select(KbIngestJob, KbDocumentVersion, KbDocument)
        .join(KbDocumentVersion, KbDocumentVersion.id == KbIngestJob.document_version_id)
        .join(KbDocument, KbDocument.id == KbDocumentVersion.document_id)
        .where(*clauses)
    )
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(KbIngestJob)
                .join(KbDocumentVersion, KbDocumentVersion.id == KbIngestJob.document_version_id)
                .join(KbDocument, KbDocument.id == KbDocumentVersion.document_id)
                .where(*clauses)
            )
        ).scalar_one()
    )
    rows = (
        await db.execute(
            base.order_by(KbIngestJob.created_at.desc(), KbIngestJob.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [
        JobSummary(
            id=job.id,
            document_id=doc.id,
            document_version_id=job.document_version_id,
            document_title=doc.title,
            version_no=version.version_no,
            job_type=job.job_type,
            status=job.status,
            progress=job.progress,
            current_stage=job.current_stage,
            attempts=job.attempts,
            error_code=job.error_code,
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            created_at=job.created_at,
        )
        for job, version, doc in rows
    ]
    return JobPage(items=items, total=total, limit=limit, offset=offset)


def _safe_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _faq_provenance(entry: FaqEntry) -> tuple[str, str]:
    flags = [str(flag) for flag in (entry.quality_flags or [])]
    dataset = (entry.source_dataset or "").lower()
    if "seeded_from_active_document" in flags or dataset.startswith("seed:"):
        return "program_seeded", "程序种子（复制原文，非专家审核）"
    if entry.reviewer:
        return "human_recorded", f"人工记录（操作人：{entry.reviewer}；未记录领域专家确认）"
    return "unrecorded", "未记录核验来源"


async def _enrich_faq_support(db: AsyncSession, entries: list[FaqEntry]) -> dict[uuid.UUID, list[FaqSupport]]:
    version_ids: set[uuid.UUID] = set()
    doc_ids: set[uuid.UUID] = set()
    for entry in entries:
        for item in entry.supporting or []:
            if not isinstance(item, dict):
                continue
            version_id = _safe_uuid(item.get("version_id"))
            document_id = _safe_uuid(item.get("document_id"))
            if version_id:
                version_ids.add(version_id)
            if document_id:
                doc_ids.add(document_id)
    versions = (
        (
            await db.execute(
                select(KbDocumentVersion).where(KbDocumentVersion.id.in_(version_ids))
            )
        )
        .scalars()
        .all()
        if version_ids
        else []
    )
    version_by_id = {version.id: version for version in versions}
    doc_ids.update(version.document_id for version in versions)
    documents = (
        (await db.execute(select(KbDocument).where(KbDocument.id.in_(doc_ids)))).scalars().all()
        if doc_ids
        else []
    )
    doc_by_id = {doc.id: doc for doc in documents}
    result: dict[uuid.UUID, list[FaqSupport]] = defaultdict(list)
    for entry in entries:
        for item in entry.supporting or []:
            if not isinstance(item, dict):
                continue
            version_id = _safe_uuid(item.get("version_id"))
            document_id = _safe_uuid(item.get("document_id"))
            version = version_by_id.get(version_id) if version_id else None
            if document_id is None and version is not None:
                document_id = version.document_id
            doc = doc_by_id.get(document_id) if document_id else None
            available = False
            reason: str | None = None
            if doc is None:
                reason = "support_document_missing"
            elif doc.status == "deleted":
                reason = "support_document_deleted"
            elif version is None:
                reason = "support_version_missing"
            elif doc.current_version_id != version.id:
                reason = "support_version_not_current"
            elif doc.verification_status != "verified":
                reason = "support_document_unverified"
            else:
                available = True
            result[entry.id].append(
                FaqSupport(
                    document_id=str(document_id) if document_id else None,
                    version_id=str(version_id) if version_id else None,
                    chunk_id=str(item.get("chunk_id")) if item.get("chunk_id") else None,
                    title=doc.title if doc else None,
                    version_no=version.version_no if version else item.get("version_no"),
                    page=item.get("page"),
                    quote=item.get("quote"),
                    score=item.get("score"),
                    source_type=(normalize_media_type(doc.source_type) if doc else None),
                    source_url=(doc.source_url if doc else None),
                    available=available,
                    unavailable_reason=reason,
                )
            )
    return result


def _to_managed_faq(entry: FaqEntry, support: list[FaqSupport]) -> ManagedFaq:
    provenance, label = _faq_provenance(entry)
    return ManagedFaq(
        id=entry.id,
        question=entry.question,
        answer=entry.answer,
        species=list(entry.species or []),
        topic=entry.topic,
        region=entry.region,
        review_status=entry.review_status,
        usage_scope=entry.usage_scope,
        evidence_status=entry.evidence_status,
        quality_flags=list(entry.quality_flags or []),
        source_dataset=entry.source_dataset or "",
        source_authority=entry.source_authority or "unknown",
        original_source_url=entry.original_source_url,
        source_license=entry.source_license,
        supporting_count=len(entry.supporting or []),
        reviewer=entry.reviewer,
        reviewed_at=entry.reviewed_at,
        indexed_at=entry.indexed_at,
        indexed=bool(entry.review_status == "verified" and entry.indexed_at is not None),
        review_provenance=provenance,
        review_provenance_label=label,
        domain_review_status="not_recorded",
        supporting=support,
    )


@router.get("/faq", response_model=FaqPage)
async def list_faq_page(
    q: str | None = Query(default=None, max_length=200),
    review_status: str | None = Query(default=None),
    evidence_status: str | None = Query(default=None),
    usage_scope: str | None = Query(default=None),
    species: str | None = Query(default=None),
    indexed: str | None = Query(default=None, pattern="^(true|false)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> FaqPage:
    clauses = []
    statuses = _split_csv(review_status)
    if statuses:
        clauses.append(FaqEntry.review_status.in_(statuses))
    evidence_values = _split_csv(evidence_status)
    if evidence_values:
        clauses.append(FaqEntry.evidence_status.in_(evidence_values))
    scopes = _split_csv(usage_scope)
    if scopes:
        clauses.append(FaqEntry.usage_scope.in_(scopes))
    for value in _split_csv(species):
        clauses.append(FaqEntry.species.any(value))
    if indexed == "true":
        clauses.append(
            (FaqEntry.review_status == "verified") & FaqEntry.indexed_at.is_not(None)
        )
    elif indexed == "false":
        # NULL-safe: a verified row whose ``indexed_at`` is NULL is *not*
        # indexed, and ``NOT (verified AND NULL)`` would silently drop it.
        clauses.append(
            or_(FaqEntry.review_status != "verified", FaqEntry.indexed_at.is_(None))
        )
    if q and q.strip():
        needle = f"%{q.strip()}%"
        clauses.append(or_(FaqEntry.question.ilike(needle), FaqEntry.answer.ilike(needle)))
    total = int(
        (await db.execute(select(func.count()).select_from(FaqEntry).where(*clauses))).scalar_one()
    )
    entries = (
        (
            await db.execute(
                select(FaqEntry)
                .where(*clauses)
                .order_by(FaqEntry.created_at.desc(), FaqEntry.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    support = await _enrich_faq_support(db, entries)
    return FaqPage(
        items=[_to_managed_faq(entry, support.get(entry.id, [])) for entry in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/faq/{faq_id}", response_model=ManagedFaq)
async def faq_detail(faq_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ManagedFaq:
    entry = await db.get(FaqEntry, faq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    support = await _enrich_faq_support(db, [entry])
    return _to_managed_faq(entry, support.get(entry.id, []))


@router.get("/faq/stats/summary")
async def faq_management_stats(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        await db.execute(
            select(FaqEntry.review_status, FaqEntry.usage_scope, FaqEntry.indexed_at)
        )
    ).mappings().all()
    by_status = Counter(str(row["review_status"]) for row in rows)
    by_scope = Counter(str(row["usage_scope"]) for row in rows)
    verified_indexed = sum(
        1
        for row in rows
        if row["review_status"] == "verified" and row["indexed_at"] is not None
    )
    points, error = await _faq_index_points()
    return {
        "total": len(rows),
        "pending": by_status.get("pending", 0),
        "verified": by_status.get("verified", 0),
        "rejected": by_status.get("rejected", 0),
        "by_status": dict(sorted(by_status.items())),
        "by_scope": dict(sorted(by_scope.items())),
        "verified_indexed": verified_indexed,
        "index_points": points,
        "index_points_error": error,
    }


@router.get("/capabilities")
async def capabilities() -> dict:
    """Server-owned feature gates, so the browser cannot widen them."""
    faq = bool(settings.enable_faq_retrieval)
    direct = bool(faq and settings.enable_faq_direct_answer)
    modes = [
        {
            "value": "document_rag",
            "label": "原文问答",
            "hint": "仅引用原始文献（默认）",
            "available": True,
            "reason": None,
        },
        {
            "value": "document_faq_rag",
            "label": "原文 + 已核验 FAQ",
            "hint": "原文不足时追加已核验 FAQ，不顶替原文",
            "available": faq,
            "reason": None if faq else "服务端未启用 FAQ 检索",
        },
        {
            "value": "faq_direct",
            "label": "FAQ 直答",
            "hint": "仅在严格条件满足时由单条已核验 FAQ 作答",
            "available": direct,
            "reason": None if direct else "服务端未启用 FAQ 直答",
        },
    ]
    return {
        "default_answer_mode": "document_rag",
        "faq_retrieval": faq,
        "faq_direct_answer": direct,
        "faq_supplement_k": settings.faq_supplement_k,
        "max_sources": settings.max_sources,
        "answer_modes": modes,
        "document_promotion": {
            "available": True,
            "requires": ["current_version_ready", "indexed_points"],
            "note": "发布仍由后端逐篇校验；本页面不提供批量发布。",
        },
    }


def _llm_endpoint_and_key() -> tuple[str, str]:
    if settings.llm_provider == "deepseek":
        return settings.deepseek_base_url, settings.deepseek_api_key
    return settings.openai_base_url, settings.openai_api_key


async def _ping_model(model: str) -> None:
    """One-token gateway call; raises with the gateway's own error on failure."""
    import httpx

    base_url, api_key = _llm_endpoint_and_key()
    if not api_key.strip() or not base_url.strip():
        raise RuntimeError("LLM 网关未配置（缺少 key 或 base_url）")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
    if response.status_code != 200:
        raise RuntimeError(f"网关返回 HTTP {response.status_code}: {response.text[:200]}")


@router.get("/llm")
async def get_llm_config(db: AsyncSession = Depends(get_db)) -> dict:
    override = await get_setting(db, LLM_MODEL_KEY)
    return {
        "provider": settings.llm_provider,
        "env_model": env_llm_model(),
        "override_model": override,
        "effective_model": override or env_llm_model(),
        "switchable": settings.llm_provider in {"openai_compatible", "openai", "deepseek"},
    }


@router.put("/llm")
async def set_llm_config(payload: LlmModelUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    if settings.llm_provider not in {"openai_compatible", "openai", "deepseek"}:
        raise HTTPException(
            status_code=400,
            detail=f"当前 provider 为 {settings.llm_provider}，没有可切换的模型",
        )
    model = payload.model.strip()
    if model:
        if any(char.isspace() for char in model):
            raise HTTPException(status_code=400, detail="模型名不能包含空白字符")
        if payload.ping:
            try:
                await _ping_model(model)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"模型验证失败：{exc}") from exc
        await set_setting(db, LLM_MODEL_KEY, model)
    else:
        await set_setting(db, LLM_MODEL_KEY, None)
    return await get_llm_config(db)
