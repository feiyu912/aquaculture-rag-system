from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from arq.connections import RedisSettings
from sqlalchemy import and_, or_, select

from app.config import settings
from app.db import SessionLocal
from app.ingestion.pipeline import ingest_version
from app.maintenance.cleanup import purge_deleted_vectors
from app.models import KbDocumentVersion, KbIngestJob
from app.retrieval.vector_store import ensure_collection

logger = logging.getLogger(__name__)


async def recover_stale_jobs(ctx: dict) -> int:
    """Re-queue jobs left running by a crashed worker.

    ARQ retries exceptions, but a hard process crash can leave a DB row in
    ``running`` with no Redis job. This is a single-worker development
    recovery pass; multi-worker deployments need a lease/heartbeat instead.
    """
    redis = ctx.get("redis")
    if redis is None:
        return 0
    running_cutoff = datetime.now(UTC) - timedelta(minutes=30)
    queued_cutoff = datetime.now(UTC) - timedelta(minutes=60)
    async with SessionLocal() as db:
        jobs = (
            (
                await db.execute(
                    select(KbIngestJob).where(
                        or_(
                            and_(
                                KbIngestJob.status == "running",
                                KbIngestJob.started_at < running_cutoff,
                            ),
                            and_(
                                KbIngestJob.status == "queued",
                                KbIngestJob.created_at < queued_cutoff,
                            ),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        for job in jobs:
            job.status = "queued"
            job.current_stage = "recovered"
            job.progress = 0
            job.attempts = 0
            version = await db.get(KbDocumentVersion, job.document_version_id)
            if version is not None and version.status not in {"ready", "failed"}:
                version.status = "processing"
        await db.commit()

    for job in jobs:
        await redis.enqueue_job(
            "ingest_version",
            str(job.document_version_id),
            _job_id=f"ingest:{job.document_version_id}:recover:{job.id}",
        )
    if jobs:
        logger.warning("recovered %s stale ingestion job(s)", len(jobs))
    return len(jobs)


async def cleanup_deleted_vectors(ctx: dict) -> dict:
    """Best-effort vector cleanup after a document is soft-deleted.

    This is intentionally idempotent and safe to retry: it only looks at
    documents whose status is already ``deleted`` and removes their derived
    points.  The manual CLI remains the fallback if Redis/ARQ is unavailable.
    """
    result = await purge_deleted_vectors(apply=True)
    logger.info("cleanup_deleted_vectors finished: %s", result)
    return result


async def startup(ctx: dict) -> None:
    ensure_collection()
    ctx["pipeline_version"] = "v1"
    await recover_stale_jobs(ctx)
    logger.info("ARQ worker ready, collection=%s", settings.qdrant_collection)


async def shutdown(ctx: dict) -> None:
    logger.info("ARQ worker stopped")


class WorkerSettings:
    functions = [ingest_version, cleanup_deleted_vectors]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.arq_queue
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3
    job_timeout = 900
    keep_result = 3600
    log_results = True
