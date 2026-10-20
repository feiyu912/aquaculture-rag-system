"""Local-only retrieval trace endpoint for debugging and experiment analysis."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
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
        "llm_planner": (log.retrieval_config or {}).get("llm_planner"),
        "active_versions": log.active_versions,
        "gate": (log.retrieval_config or {}).get("evidence_gate"),
        "timings": log.timings,
        "rankings": {key: value for key, value in rankings.items() if key != "fused"},
        "fused": rankings.get("fused") or [],
        "fused_count": len(rankings.get("fused") or []),
        "evidence": log.evidence,
        "citation_check": log.citation_check,
        "model": log.llm_model,
        "cost_usd": log.cost_usd,
    }


@router.get("/stats")
async def get_stats(
    hours: int = Query(default=24, ge=1, le=24 * 30),
    limit: int = Query(default=1000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate retrieval/answer telemetry for the dashboard.

    Questions and answers are deliberately excluded; use the per-request trace
    endpoint for debugging a single request.
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    logs = (
        (
            await db.execute(
                select(QueryLog)
                .where(QueryLog.created_at >= since)
                .order_by(QueryLog.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    total = len(logs)
    routes: dict[str, int] = {}
    models: dict[str, int] = {}
    refusals = 0
    retrieval_ms: list[float] = []
    total_ms: list[float] = []
    prompt_tokens = 0
    completion_tokens = 0
    cost = 0.0
    for log in logs:
        routes[log.route or "unknown"] = routes.get(log.route or "unknown", 0) + 1
        model = log.llm_model or "unknown"
        models[model] = models.get(model, 0) + 1
        gate = (log.retrieval_config or {}).get("evidence_gate") or {}
        if gate.get("sufficient") is False:
            refusals += 1
        timings = log.timings or {}
        if timings.get("retrieval_ms") is not None:
            retrieval_ms.append(float(timings["retrieval_ms"]))
        if timings.get("total_ms") is not None:
            total_ms.append(float(timings["total_ms"]))
        usage = log.token_usage or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        cost += float(log.cost_usd or 0.0)

    def _p95(values: list[float]) -> float:
        if not values:
            return 0.0
        index = max(0, int(len(values) * 0.95) - 1)
        return round(sorted(values)[index], 1)

    return {
        "window_hours": hours,
        "queries": total,
        "refusals": refusals,
        "refusal_rate": round(refusals / total, 3) if total else 0.0,
        "routes": dict(sorted(routes.items())),
        "models": dict(sorted(models.items())),
        "avg_retrieval_ms": round(statistics.mean(retrieval_ms), 1) if retrieval_ms else 0.0,
        "p95_retrieval_ms": _p95(retrieval_ms),
        "avg_total_ms": round(statistics.mean(total_ms), 1) if total_ms else 0.0,
        "p95_total_ms": _p95(total_ms),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": round(cost, 6),
    }
