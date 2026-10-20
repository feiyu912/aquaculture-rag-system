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
    (
        "0008_chunk_context_text",
        "ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS context_text text",
    ),
    (
        "0009_graph_entities",
        """CREATE TABLE IF NOT EXISTS graph_entities (
            id uuid PRIMARY KEY,
            name text NOT NULL UNIQUE,
            entity_type varchar(32) NOT NULL,
            description text NOT NULL DEFAULT '',
            review_status varchar(16) NOT NULL DEFAULT 'verified',
            created_at timestamptz NOT NULL DEFAULT now()
        )""",
    ),
    (
        "0010_graph_aliases",
        """CREATE TABLE IF NOT EXISTS graph_aliases (
            id uuid PRIMARY KEY,
            entity_id uuid NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
            alias text NOT NULL UNIQUE,
            review_status varchar(16) NOT NULL DEFAULT 'verified',
            created_at timestamptz NOT NULL DEFAULT now()
        )""",
    ),
    (
        "0011_graph_relations",
        """CREATE TABLE IF NOT EXISTS graph_relations (
            id uuid PRIMARY KEY,
            source_entity_id uuid NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
            target_entity_id uuid NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
            relation_type varchar(32) NOT NULL,
            provenance_document_version_id uuid,
            confidence double precision NOT NULL DEFAULT 1.0,
            review_status varchar(16) NOT NULL DEFAULT 'verified',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_graph_relation UNIQUE (source_entity_id, target_entity_id, relation_type)
        )""",
    ),
    (
        "0013_index_manifests",
        """CREATE TABLE IF NOT EXISTS index_manifests (
            collection varchar(128) PRIMARY KEY,
            embedding_model varchar(128) NOT NULL,
            vector_size integer NOT NULL,
            chunk_config_hash varchar(64) NOT NULL DEFAULT '',
            status varchar(16) NOT NULL DEFAULT 'building',
            document_count integer NOT NULL DEFAULT 0,
            point_count integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )""",
    ),
    (
        "0012_chunk_entities",
        """CREATE TABLE IF NOT EXISTS kb_chunk_entities (
            chunk_id uuid NOT NULL REFERENCES kb_chunks(id) ON DELETE CASCADE,
            entity_id uuid NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
            mention_count integer NOT NULL DEFAULT 1,
            PRIMARY KEY (chunk_id, entity_id)
        )""",
    ),
    (
        "0014_manifest_bm25_config_hash",
        """ALTER TABLE index_manifests ADD COLUMN IF NOT EXISTS
        bm25_config_hash varchar(64) NOT NULL DEFAULT ''""",
    ),
    (
        "0015_document_deleted_at",
        "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS deleted_at timestamptz",
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
