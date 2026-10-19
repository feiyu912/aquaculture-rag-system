from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Lightweight additive migrations for the development skeleton.
# Production should move to Alembic before destructive schema changes.
MIGRATIONS: list[tuple[str, str]] = [
    (
        "0001_document_species",
        """ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS
        species text[] NOT NULL DEFAULT '{}'::text[]""",
    ),
    (
        "0002_citation_support_score",
        "ALTER TABLE chat_citations ADD COLUMN IF NOT EXISTS support_score double precision",
    ),
    (
        "0003_query_log_retrieval_rankings",
        """ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS
        retrieval_rankings jsonb NOT NULL DEFAULT '{}'::jsonb""",
    ),
    (
        "0004_query_log_evidence",
        """ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS
        evidence jsonb NOT NULL DEFAULT '[]'::jsonb""",
    ),
    (
        "0005_query_log_llm_model",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS llm_model text",
    ),
    (
        "0006_query_log_generation_config",
        """ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS
        generation_config jsonb NOT NULL DEFAULT '{}'::jsonb""",
    ),
    (
        "0007_query_log_cost",
        "ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS cost_usd double precision",
    ),
]


async def apply_migrations(conn: AsyncConnection) -> list[str]:
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version text PRIMARY KEY, "
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
    )
    applied: list[str] = []
    for version, statement in MIGRATIONS:
        exists = await conn.scalar(
            text("SELECT 1 FROM schema_migrations WHERE version = :version"),
            {"version": version},
        )
        if exists:
            continue
        await conn.execute(text(statement))
        await conn.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"),
            {"version": version},
        )
        applied.append(version)
    return applied