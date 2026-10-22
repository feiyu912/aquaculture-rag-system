from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Lightweight additive migrations for the development skeleton.
# Production should move to Alembic before destructive schema changes.
#
# A migration is either one SQL statement or a list of statements.  asyncpg
# rejects multiple statements in a single prepared statement, so multi-step
# DDL must be expressed as a list.
MIGRATIONS: list[tuple[str, str | list[str]]] = [
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
    # --- Data construction (2026-10-21) ---------------------------------
    (
        "0016_document_provenance",
        """ALTER TABLE kb_documents
             ADD COLUMN IF NOT EXISTS source_type varchar(16) NOT NULL DEFAULT 'pdf',
             ADD COLUMN IF NOT EXISTS authority_level varchar(32) NOT NULL DEFAULT 'unknown',
             ADD COLUMN IF NOT EXISTS fetched_at timestamptz,
             ADD COLUMN IF NOT EXISTS effective_date varchar(32),
             ADD COLUMN IF NOT EXISTS growth_stages text[] NOT NULL DEFAULT '{}'::text[],
             ADD COLUMN IF NOT EXISTS region varchar(64),
             ADD COLUMN IF NOT EXISTS supersedes_document_id uuid""",
    ),
    (
        "0017_faq_entries",
        """CREATE TABLE IF NOT EXISTS faq_entries (
            id uuid PRIMARY KEY,
            question text NOT NULL,
            answer text NOT NULL,
            question_norm text NOT NULL,
            question_hash varchar(64) NOT NULL,
            species text[] NOT NULL DEFAULT '{}'::text[],
            topic varchar(64),
            growth_stages text[] NOT NULL DEFAULT '{}'::text[],
            region varchar(64),
            source_dataset text NOT NULL DEFAULT '',
            original_id varchar(128),
            original_source_url text,
            source_license varchar(64),
            original_answer text,
            supporting jsonb NOT NULL DEFAULT '[]'::jsonb,
            evidence_status varchar(16) NOT NULL DEFAULT 'none',
            quality_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
            cluster_id varchar(64),
            review_status varchar(16) NOT NULL DEFAULT 'pending',
            usage_scope varchar(16) NOT NULL DEFAULT 'knowledge',
            confidence double precision,
            review_notes text,
            reviewer varchar(64),
            reviewed_at timestamptz,
            content_hash varchar(64) NOT NULL,
            indexed_at timestamptz,
            index_collection varchar(128),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_faq_question_hash UNIQUE (question_hash)
        )""",
    ),
    (
        "0018_data_runs",
        """CREATE TABLE IF NOT EXISTS data_runs (
            id uuid PRIMARY KEY,
            kind varchar(24) NOT NULL,
            status varchar(16) NOT NULL DEFAULT 'running',
            params jsonb NOT NULL DEFAULT '{}'::jsonb,
            stats jsonb NOT NULL DEFAULT '{}'::jsonb,
            error_message text,
            started_at timestamptz,
            finished_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )""",
    ),
    (
        "0019_citation_source_type",
        """ALTER TABLE chat_citations
             ALTER COLUMN document_id DROP NOT NULL,
             ALTER COLUMN document_version_id DROP NOT NULL,
             ADD COLUMN IF NOT EXISTS source_type varchar(16) NOT NULL DEFAULT 'document',
             ADD COLUMN IF NOT EXISTS faq_id uuid""",
    ),
    (
        "0021_document_verification",
        """ALTER TABLE kb_documents
             ADD COLUMN IF NOT EXISTS verification_status varchar(16) NOT NULL DEFAULT 'verified',
             ADD COLUMN IF NOT EXISTS superseded_by_document_id uuid""",
    ),
    (
        "0022_faq_source_authority",
        "ALTER TABLE faq_entries ADD COLUMN IF NOT EXISTS source_authority varchar(32) NOT NULL DEFAULT 'unknown'",
    ),
    (
        "0025_index_eligibility",
        [
            "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS source_trust varchar(24)",
            "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS index_eligibility varchar(24)",
            "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS risk_level varchar(16)",
            "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS licence_class varchar(32)",
            "CREATE INDEX IF NOT EXISTS ix_kb_docs_eligibility ON kb_documents (index_eligibility)",
        ],
    ),
    (
        "0024_data_items",
        [
            """CREATE TABLE IF NOT EXISTS data_items (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                source_id varchar(80),
                url text NOT NULL UNIQUE,
                final_url text,
                title text,
                kind varchar(16) NOT NULL DEFAULT 'html',
                license varchar(120),
                storage_policy varchar(24) NOT NULL DEFAULT 'full_text',
                sha256 varchar(64),
                simhash varchar(32),
                state varchar(24) NOT NULL DEFAULT 'discovered',
                attempts integer NOT NULL DEFAULT 0,
                last_error text,
                next_retry_at timestamptz,
                document_id uuid,
                bytes bigint,
                fetched_at timestamptz,
                meta jsonb NOT NULL DEFAULT '{}'::jsonb,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_data_items_state ON data_items (state)",
            "CREATE INDEX IF NOT EXISTS ix_data_items_source ON data_items (source_id, state)",
            "CREATE INDEX IF NOT EXISTS ix_data_items_sha ON data_items (sha256)",
        ],
    ),
    (
        "0023_document_review_status",
        [
            "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS technical_review_status varchar(16) NOT NULL DEFAULT 'pending'",
            "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS domain_review_status varchar(16) NOT NULL DEFAULT 'pending'",
            "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS review_flags jsonb NOT NULL DEFAULT '[]'::jsonb",
            "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS reviewed_at timestamptz",
            "CREATE INDEX IF NOT EXISTS ix_kb_documents_technical_review ON kb_documents (technical_review_status)",
        ],
    ),
    (
        "0020_document_indexes",
        [
            "CREATE INDEX IF NOT EXISTS ix_kb_documents_source_type ON kb_documents (source_type)",
            "CREATE INDEX IF NOT EXISTS ix_kb_documents_authority ON kb_documents (authority_level)",
            "CREATE INDEX IF NOT EXISTS ix_faq_review_status ON faq_entries (review_status)",
            "CREATE INDEX IF NOT EXISTS ix_faq_cluster ON faq_entries (cluster_id)",
            "CREATE INDEX IF NOT EXISTS ix_faq_scope ON faq_entries (usage_scope)",
            "CREATE INDEX IF NOT EXISTS ix_citations_faq ON chat_citations (faq_id)",
            "CREATE INDEX IF NOT EXISTS ix_data_runs_kind ON data_runs (kind, created_at)",
        ],
    ),
    (
        "0026_app_settings",
        """CREATE TABLE IF NOT EXISTS app_settings (
            key varchar(64) PRIMARY KEY,
            value text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )""",
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
        statements = [statement] if isinstance(statement, str) else list(statement)
        for sql in statements:
            await conn.execute(text(sql))
        await conn.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"),
            {"version": version},
        )
        applied.append(version)
    return applied
