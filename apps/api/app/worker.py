from __future__ import annotations

import logging

from arq.connections import RedisSettings

from app.config import settings
from app.ingestion.pipeline import ingest_version
from app.retrieval.vector_store import ensure_collection

logger = logging.getLogger(__name__)


async def startup(ctx: dict) -> None:
    ensure_collection()
    ctx["pipeline_version"] = "v1"
    logger.info("ARQ worker ready, collection=%s", settings.qdrant_collection)


async def shutdown(ctx: dict) -> None:
    logger.info("ARQ worker stopped")


class WorkerSettings:
    functions = [ingest_version]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.arq_queue
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3
    job_timeout = 900
    keep_result = 3600
    log_results = True
