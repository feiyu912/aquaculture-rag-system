"""Read-only endpoints over the collection registry and import runs.

These back the "数据来源" panel: which sources exist, how each was classified,
and whether its material is still staged or already published.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.collection.registry import load_registry
from app.config import settings
from app.db import get_db
from app.models import DataRun

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/sources")
async def list_sources(db: AsyncSession = Depends(get_db)) -> dict:
    registry_path = settings.data_path.parent / "sources" / "registry.yaml"
    if not registry_path.exists():
        registry_path = settings.data_path / "sources" / "registry.yaml"
    specs = load_registry(registry_path) if registry_path.exists() else []

    counts = (
        await db.execute(
            text(
                """
                SELECT metadata->>'source_id' AS source_id,
                       count(*) FILTER (WHERE status = 'active')    AS active,
                       count(*) FILTER (WHERE status = 'staging')   AS staging,
                       sum((SELECT count(*) FROM kb_chunks c
                            WHERE c.document_version_id = d.current_version_id)) AS chunks
                FROM kb_documents d
                WHERE metadata ? 'source_id'
                GROUP BY 1
                """
            )
        )
    ).mappings().all()
    by_source = {row["source_id"]: dict(row) for row in counts}

    items = []
    for spec in specs:
        stat = by_source.get(spec.id, {})
        items.append(
            {
                **spec.as_dict(),
                "documents_active": int(stat.get("active") or 0),
                "documents_staging": int(stat.get("staging") or 0),
                "chunks": int(stat.get("chunks") or 0),
            }
        )
    return {
        "total": len(items),
        "by_authority": _count_by(items, "authority"),
        "by_policy": _count_by(items, "policy"),
        "items": items,
    }


def _count_by(items: list[dict], key: str) -> dict:
    result: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        result[value] = result.get(value, 0) + 1
    return result


@router.get("/runs")
async def list_runs(
    kind: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    from sqlalchemy import select

    statement = select(DataRun).order_by(DataRun.created_at.desc()).limit(limit)
    if kind:
        statement = statement.where(DataRun.kind == kind)
    rows = (await db.execute(statement)).scalars().all()
    return [
        {
            "id": str(row.id),
            "kind": row.kind,
            "status": row.status,
            "params": row.params,
            "stats": row.stats,
            "error_message": row.error_message,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
        }
        for row in rows
    ]