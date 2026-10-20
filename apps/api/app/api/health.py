from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.retrieval.vector_store import get_client

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    components: dict[str, str] = {}
    try:
        await db.execute(text("SELECT 1"))
        components["postgres"] = "ok"
    except Exception as exc:
        components["postgres"] = f"error: {exc.__class__.__name__}"

    try:
        client = get_client()
        client.get_collections()
        client.close()
        components["qdrant"] = "ok"
    except Exception as exc:
        components["qdrant"] = f"error: {exc.__class__.__name__}"

    pool = getattr(request.app.state, "arq_pool", None)
    if pool is None:
        components["redis"] = "unavailable"
    else:
        try:
            await pool.ping()
            components["redis"] = "ok"
        except Exception as exc:
            components["redis"] = f"error: {exc.__class__.__name__}"

    status = "ok" if all(value == "ok" for value in components.values()) else "degraded"
    return {
        "status": status,
        "components": components,
        "collection": settings.qdrant_collection,
        "llm_provider": settings.llm_provider,
        "llm_configured": (
            bool(settings.deepseek_api_key.strip())
            if settings.llm_provider == "deepseek"
            else (
                bool(
                    settings.openai_api_key.strip()
                    and settings.openai_base_url.strip()
                    and settings.openai_model.strip()
                )
                if settings.llm_provider in {"openai_compatible", "openai"}
                else True
            )
        ),
        "embedding_model": settings.embedding_model,
        "embedding_device": settings.embedding_device,
        "reranker_model": settings.reranker_model,
        # Retrieval limits the UI should surface instead of guessing.
        "max_sources": settings.max_sources,
        "rerank_top_k": settings.rerank_top_k,
    }
