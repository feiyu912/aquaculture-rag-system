from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import KbDocument, KbDocumentVersion, KbIngestJob
from app.retrieval.vector_store import count_version_points, get_client
from app.schemas import (
    DocumentDetail,
    DocumentOut,
    JobOut,
    RollbackRequest,
    UploadResponse,
    VersionOut,
)

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
        status=doc.status,
        current_version_id=doc.current_version_id,
        current_version_no=version.version_no if version else None,
        page_count=version.page_count if version else None,
        created_at=doc.created_at,
    )


@router.post("/documents", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str = Form(default="未分类"),
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

    doc = KbDocument(
        id=doc_id,
        title=safe_title,
        category=category.strip() or "未分类",
        status="active",
        doc_metadata={"original_filename": filename, "size_bytes": len(buffer)},
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
        raise HTTPException(status_code=503, detail="任务队列不可用，请检查 Redis")
    await pool.enqueue_job("ingest_version", str(version_id), _job_id=f"ingest:{version_id}:v1")
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


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(db: AsyncSession = Depends(get_db)) -> list[DocumentOut]:
    docs = (
        (
            await db.execute(
                select(KbDocument)
                .where(KbDocument.status != "deleted")
                .order_by(KbDocument.created_at.desc())
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
async def delete_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    doc = await db.get(KbDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    doc.status = "deleted"
    doc.current_version_id = None
    versions = (
        (
            await db.execute(
                select(KbDocumentVersion).where(
                    KbDocumentVersion.document_id == document_id,
                    KbDocumentVersion.status == "ready",
                )
            )
        )
        .scalars()
        .all()
    )
    for version in versions:
        version.status = "archived"
    await db.commit()


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
