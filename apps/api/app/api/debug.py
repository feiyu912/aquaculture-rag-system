"""Local-only retrieval trace endpoint for debugging and experiment analysis."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import QueryLog

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/query-logs/{request_id}")
async def get_query_trace(request_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    log = (
        await db.execute(select(QueryLog).where(QueryLog.request_id == request_id))
    ).scalar_one_or_none()
    if log is None:
        raise HTTPException(status_code=404, detail="查询日志不存在")
    rankings = log.retrieval_rankings or {}
    return {
        "request_id": log.request_id,
        "question": log.question,
        "retrieval_config": log.retrieval_config,
        "query_ir": (log.retrieval_config or {}).get("query_ir"),
        "active_versions": log.active_versions,
        "gate": (log.retrieval_config or {}).get("evidence_gate"),
        "timings": log.timings,
        "rankings": {key: value for key, value in rankings.items() if key != "fused"},
        "fused_count": len(rankings.get("fused") or []),
        "evidence": log.evidence,
        "citation_check": log.citation_check,
        "model": log.llm_model,
        "cost_usd": log.cost_usd,
    }
