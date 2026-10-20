from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import (
    ChatCitation,
    ChatMessage,
    ChatSession,
    KbDocument,
    KbDocumentVersion,
    KbIngestJob,
)
from app.retrieval.vector_store import count_version_points, get_client
from app.schemas import (
    DocumentCitationOut,
    DocumentDetail,
    DocumentOut,
    JobOut,
    RollbackRequest,
    UploadResponse,
    VersionOut,
)
from app.species import GENERAL_SPECIES, normalize_species_list, parse_species

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["documents"])

PDF_TYPES = {"application/pdf", "application/octet-stream", "binary/octet-stream"}


def _version_out(version: KbDocumentVersion) -> VersionOut:
    return VersionOut(
        id=version.id,
        version_no=version.version_no,
        status=version.status,
        page_count=version.page_count,
        content_hash=version.content_hash,
        error_message=version.error_message,
        created_at=version.created_at,
        activated_at=version.activated_at,
    )


def _doc_out(doc: KbDocument, version: KbDocumentVersion | None) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        title=doc.title,
        category=doc.category,
        species=normalize_species_list(doc.species),
        status=doc.status,
        current_version_id=doc.current_version_id,
        current_version_no=version.version_no if version else None,
        page_count=version.page_count if version else None,
        created_at=doc.created_at,
        source_org=doc.source_org,
        source_url=doc.source_url,
        publish_year=doc.publish_year,
        document_status=(doc.doc_metadata or {}).get("document_status"),
        region=(doc.doc_metadata or {}).get("region"),
    )


@router.post("/documents", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str = Form(default="未分类"),
    species: str | None = Form(default=None),
    source_org: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    publish_year: int | None = Form(default=None),
    document_status: str | None = Form(default=None),
    region: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="仅支持 PDF 文件")
    if file.content_type and file.content_type not in PDF_TYPES:
        raise HTTPException(status_code=415, detail=f"不支持的文件类型: {file.content_type}")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    buffer = bytearray()
    while chunk := await file.read(1024 * 1024):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_upload_mb} MB")
    if not buffer:
        raise HTTPException(status_code=400, detail="空文件")
    if not buffer.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="文件不是有效的 PDF")

    content_hash = hashlib.sha256(buffer).hexdigest()
    duplicate = (
        (
            await db.execute(
                select(KbDocumentVersion)
                .join(KbDocument, KbDocument.id == KbDocumentVersion.document_id)
                .where(
                    KbDocumentVersion.content_hash == content_hash,
                    KbDocumentVersion.status.in_(["processing", "ready"]),
                    KbDocument.status != "deleted",
                )
            )
        )
        .scalars()
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "相同内容的文件已存在",
                "document_id": str(duplicate.document_id),
                "version_id": str(duplicate.id),
            },
        )

    doc_id = uuid.uuid4()
    version_id = uuid.uuid4()
    job_id = uuid.uuid4()
    safe_title = (title or Path(filename).stem).strip() or "未命名文档"
    relative = Path("documents") / str(doc_id) / str(version_id) / "original.pdf"
    target = settings.data_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_bytes, bytes(buffer))

    try:
        species_list = parse_species(species)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if publish_year is not None and not 1900 <= publish_year <= 2100:
        raise HTTPException(status_code=400, detail="publish_year 必须在 1900–2100 之间")

    doc = KbDocument(
        id=doc_id,
        title=safe_title,
        category=category.strip() or "未分类",
        species=species_list,
        source_org=(source_org or "").strip() or None,
        source_url=(source_url or "").strip() or None,
        publish_year=publish_year,
        status="active",
        doc_metadata={
            "original_filename": filename,
            "size_bytes": len(buffer),
            "document_status": (document_status or "").strip() or None,
            "region": (region or "").strip() or None,
        },
    )
    version = KbDocumentVersion(
        id=version_id,
        document_id=doc_id,
        version_no=1,
        content_hash=content_hash,
        file_path=str(target),
        file_size=len(buffer),
        status="processing",
        parser_name="pymupdf",
    )
    job = KbIngestJob(
        id=job_id,
        document_version_id=version_id,
        job_type="ingest",
        status="queued",
        current_stage="queued",
        idempotency_key=f"ingest:{version_id}:v1",
    )
    db.add_all([doc, version, job])
    await db.commit()

    pool = getattr(request.app.state, "arq_pool", None)
    if pool is None:
        job.status = "failed"
        job.error_code = "queue_unavailable"
        job.error_message = "Redis/ARQ unavailable"
        await db.commit()
        raise HTTPException(status_code=503, detail="任务队列不可用，请检查 Redis")

    try:
        await pool.enqueue_job(
            "ingest_version",
            str(version_id),
            _job_id=f"ingest:{version_id}:v1",
        )
    except Exception as exc:
        job.status = "failed"
        job.error_code = "enqueue_failed"
        job.error_message = str(exc)[:500]
        await db.commit()
        raise HTTPException(status_code=503, detail="任务入队失败") from exc

    return UploadResponse(document_id=doc_id, version_id=version_id, job_id=job_id, status="queued")


@router.post(
    "/documents/{document_id}/versions",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def add_version(
    request: Request,
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    doc = await db.get(KbDocument, document_id)
    if doc is None or doc.status == "deleted":
        raise HTTPException(status_code=404, detail="文档不存在")
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="仅支持 PDF 文件")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    buffer = bytearray()
    while chunk := await file.read(1024 * 1024):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_upload_mb} MB")
    if not buffer.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="文件不是有效的 PDF")
    content_hash = hashlib.sha256(buffer).hexdigest()

    duplicate = (
        (
            await db.execute(
                select(KbDocumentVersion).where(
                    KbDocumentVersion.document_id == document_id,
                    KbDocumentVersion.content_hash == content_hash,
                    KbDocumentVersion.status.in_(["processing", "ready", "archived"]),
                )
            )
        )
        .scalars()
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "该文档已存在相同内容的版本",
                "version_id": str(duplicate.id),
            },
        )

    # Serialize version-number allocation for the same document. The file has
    # already been read, so this lock is held only for the metadata transaction.
    doc = (
        await db.execute(select(KbDocument).where(KbDocument.id == document_id).with_for_update())
    ).scalar_one_or_none()
    if doc is None or doc.status == "deleted":
        raise HTTPException(status_code=404, detail="文档不存在")
    max_no = (
        await db.execute(
            select(func.max(KbDocumentVersion.version_no)).where(
                KbDocumentVersion.document_id == document_id
            )
        )
    ).scalar_one()
    version_id = uuid.uuid4()
    job_id = uuid.uuid4()
    target = settings.data_path / "documents" / str(document_id) / str(version_id) / "original.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_bytes, bytes(buffer))

    version = KbDocumentVersion(
        id=version_id,
        document_id=document_id,
        version_no=(max_no or 0) + 1,
        content_hash=content_hash,
        file_path=str(target),
        file_size=len(buffer),
        status="processing",
        parser_name="pymupdf",
    )
    job = KbIngestJob(
        id=job_id,
        document_version_id=version_id,
        job_type="ingest",
        status="queued",
        current_stage="queued",
        idempotency_key=f"ingest:{version_id}:v1",
    )
    db.add_all([version, job])
    await db.commit()

    pool = getattr(request.app.state, "arq_pool", None)
    if pool is None:
        version.status = "failed"
        version.error_code = "queue_unavailable"
        version.error_message = "Redis/ARQ unavailable"
        job.status = "failed"
        job.error_code = "queue_unavailable"
        job.error_message = "Redis/ARQ unavailable"
        await db.commit()
        raise HTTPException(status_code=503, detail="任务队列不可用，请检查 Redis")
    try:
        await pool.enqueue_job("ingest_version", str(version_id), _job_id=f"ingest:{version_id}:v1")
    except Exception as exc:
        version.status = "failed"
        version.error_code = "enqueue_failed"
        version.error_message = str(exc)[:500]
        job.status = "failed"
        job.error_code = "enqueue_failed"
        job.error_message = str(exc)[:500]
        await db.commit()
        raise HTTPException(status_code=503, detail="任务入队失败") from exc
    return UploadResponse(
        document_id=document_id, version_id=version_id, job_id=job_id, status="queued"
    )


@router.post("/documents/{document_id}/rollback", response_model=DocumentOut)
async def rollback_version(
    document_id: uuid.UUID,
    payload: RollbackRequest,
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    doc = (
        await db.execute(select(KbDocument).where(KbDocument.id == document_id).with_for_update())
    ).scalar_one_or_none()
    if doc is None or doc.status == "deleted":
        raise HTTPException(status_code=404, detail="文档不存在")
    version = await db.get(KbDocumentVersion, payload.version_id)
    if version is None or version.document_id != document_id:
        raise HTTPException(status_code=404, detail="版本不存在")
    if version.id == doc.current_version_id:
        return _doc_out(doc, version)
    if version.status not in {"ready", "archived"}:
        raise HTTPException(status_code=409, detail="该版本尚未成功入库，无法回滚")

    client = get_client()
    try:
        indexed = await asyncio.to_thread(count_version_points, client, version.id)
    finally:
        client.close()
    if indexed == 0:
        raise HTTPException(status_code=409, detail="该版本向量已清理，需要重新索引后才能回滚")

    current = (
        await db.get(KbDocumentVersion, doc.current_version_id) if doc.current_version_id else None
    )
    if current is not None and current.id != version.id:
        current.status = "archived"
        current.archived_at = datetime.now(UTC)
    version.status = "ready"
    version.activated_at = datetime.now(UTC)
    doc.current_version_id = version.id
    doc.status = "active"
    await db.commit()
    return _doc_out(doc, version)


@router.get("/species", response_model=list[str])
async def list_species(db: AsyncSession = Depends(get_db)) -> list[str]:
    rows = (
        await db.execute(
            select(KbDocument.species).where(
                KbDocument.status == "active", KbDocument.current_version_id.is_not(None)
            )
        )
    ).all()
    values: set[str] = set()
    for (species,) in rows:
        values.update(normalize_species_list(species))
    ordered = sorted(value for value in values if value != GENERAL_SPECIES)
    return [GENERAL_SPECIES, *ordered]


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    q: str | None = Query(default=None, max_length=200),
    doc_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentOut]:
    statement = select(KbDocument).where(KbDocument.status != "deleted")
    if doc_status:
        statement = statement.where(KbDocument.status == doc_status)
    if q:
        statement = statement.where(KbDocument.title.ilike(f"%{q.strip()}%"))
    docs = (
        (
            await db.execute(
                statement.order_by(KbDocument.created_at.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    version_ids = [doc.current_version_id for doc in docs if doc.current_version_id]
    versions = (
        (await db.execute(select(KbDocumentVersion).where(KbDocumentVersion.id.in_(version_ids))))
        .scalars()
        .all()
        if version_ids
        else []
    )
    version_by_id = {version.id: version for version in versions}
    return [
        _doc_out(doc, version_by_id.get(doc.current_version_id) if doc.current_version_id else None)
        for doc in docs
    ]


@router.get("/documents/{document_id}/citations", response_model=list[DocumentCitationOut])
async def list_document_citations(
    document_id: uuid.UUID,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentCitationOut]:
    """Citations in past answers that point at this document.

    The reader uses this to show *why* a document was cited and to jump back
    to the originating conversation.
    """
    doc = await db.get(KbDocument, document_id)
    if doc is None or doc.status == "deleted":
        raise HTTPException(status_code=404, detail="文档不存在")

    rows = (
        await db.execute(
            select(ChatCitation, ChatMessage, ChatSession)
            .join(ChatMessage, ChatMessage.id == ChatCitation.message_id)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatCitation.document_id == document_id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatCitation.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    if not rows:
        return []

    version_ids = {row[0].document_version_id for row in rows}
    versions = (
        (await db.execute(select(KbDocumentVersion).where(KbDocumentVersion.id.in_(version_ids))))
        .scalars()
        .all()
        if version_ids
        else []
    )
    version_numbers = {version.id: version.version_no for version in versions}

    return [
        DocumentCitationOut(
            id=citation.id,
            source_index=citation.source_index,
            document_id=citation.document_id,
            document_version_id=citation.document_version_id,
            quote=citation.quote,
            page=citation.page,
            bbox=citation.bbox,
            score=citation.score,
            support_status=citation.support_status,
            support_score=citation.support_score,
            title=doc.title,
            version_no=version_numbers.get(citation.document_version_id),
            species=normalize_species_list(doc.species),
            message_id=message.id,
            session_id=session.id,
            question=session.title,
            answer_preview=(message.content or "")[:200],
            cited_at=citation.created_at,
        )
        for citation, message, session in rows
    ]


@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> DocumentDetail:
    doc = await db.get(KbDocument, document_id)
    if doc is None or doc.status == "deleted":
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
    current = next((v for v in versions if v.id == doc.current_version_id), None)
    base = _doc_out(doc, current)
    return DocumentDetail(**base.model_dump(), versions=[_version_out(v) for v in versions])


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    request: Request, document_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    doc = await db.get(KbDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    doc.status = "deleted"
    doc.deleted_at = datetime.now(UTC)
    doc.current_version_id = None
    versions = (
        (
            await db.execute(
                select(KbDocumentVersion).where(KbDocumentVersion.document_id == document_id)
            )
        )
        .scalars()
        .all()
    )
    for version in versions:
        if version.status != "failed":
            version.status = "archived"
    jobs = (
        (
            await db.execute(
                select(KbIngestJob).where(
                    KbIngestJob.document_version_id.in_([version.id for version in versions]),
                    KbIngestJob.status.in_(["queued", "running"]),
                )
            )
        )
        .scalars()
        .all()
        if versions
        else []
    )
    for job in jobs:
        job.status = "cancelled"
        job.current_stage = "cancelled"
        job.error_code = "document_deleted"
        job.error_message = "文档已删除，任务取消"
        job.finished_at = datetime.now(UTC)
    await db.commit()

    # Vector cleanup is derived work: the DB rows/files stay for retention and
    # audit. Enqueue best-effort; a missing queue must not turn a successful
    # soft-delete into an HTTP error. The CLI can always finish the cleanup.
    pool = getattr(request.app.state, "arq_pool", None)
    if pool is not None:
        try:
            await pool.enqueue_job(
                "cleanup_deleted_vectors",
                _job_id=f"cleanup:{document_id}:{uuid.uuid4().hex[:8]}",
            )
        except Exception as exc:  # pragma: no cover - depends on Redis failure
            logger.warning("failed to enqueue cleanup for %s: %s", document_id, exc)


@router.get("/documents/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID, version_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)
):
    doc = await db.get(KbDocument, document_id)
    if doc is None or doc.status == "deleted":
        raise HTTPException(status_code=404, detail="文档不存在")
    target_version_id = version_id or doc.current_version_id
    if target_version_id is None:
        raise HTTPException(status_code=404, detail="文档没有可用版本")
    version = await db.get(KbDocumentVersion, target_version_id)
    if version is None or version.document_id != document_id:
        raise HTTPException(status_code=404, detail="版本不存在")
    path = Path(version.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="原始文件已丢失")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{doc.title}.pdf",
        content_disposition_type="inline",
    )


@router.post("/jobs/{job_id}/retry", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def retry_job(
    job_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    job = await db.get(KbIngestJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="只有失败任务可以重试")
    version = await db.get(KbDocumentVersion, job.document_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="版本不存在")

    version.status = "processing"
    version.error_code = None
    version.error_message = None
    job.status = "queued"
    job.progress = 0
    job.current_stage = "queued"
    job.attempts = 0
    job.error_code = None
    job.error_message = None
    job.started_at = None
    job.finished_at = None
    await db.commit()

    pool = getattr(request.app.state, "arq_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="任务队列不可用，请检查 Redis")
    try:
        await pool.enqueue_job(
            "ingest_version",
            str(version.id),
            _job_id=f"ingest:{version.id}:retry:{job_id}",
        )
    except Exception as exc:
        job.status = "failed"
        job.error_code = "enqueue_failed"
        job.error_message = str(exc)[:500]
        version.status = "failed"
        version.error_code = "enqueue_failed"
        version.error_message = str(exc)[:500]
        await db.commit()
        raise HTTPException(status_code=503, detail="任务入队失败") from exc
    return JobOut(
        id=job.id,
        document_version_id=job.document_version_id,
        status=job.status,
        progress=job.progress,
        current_stage=job.current_stage,
        error_code=job.error_code,
        error_message=job.error_message,
        metrics=job.metrics or {},
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> JobOut:
    job = await db.get(KbIngestJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JobOut(
        id=job.id,
        document_version_id=job.document_version_id,
        status=job.status,
        progress=job.progress,
        current_stage=job.current_stage,
        error_code=job.error_code,
        error_message=job.error_message,
        metrics=job.metrics or {},
    )
