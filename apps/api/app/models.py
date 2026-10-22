from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KbDocument(Base, TimestampMixin):
    __tablename__ = "kb_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="未分类")
    species: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    source_org: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    publish_year: Mapped[int | None] = mapped_column(Integer)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # active | staging | deleted.  Retrieval derives its version filter from
    # ``status == "active"``, so a staged document is indexed but invisible.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Provenance / applicability metadata.  Distinct from ``publish_year``:
    # a web page needs the *fetch* time, and a standard needs its effective
    # date; neither can be inferred from the other.
    source_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pdf", server_default="pdf"
    )
    authority_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_date: Mapped[str | None] = mapped_column(String(32))
    # Applicability is metadata, never a hard filter unless the user asks for it.
    growth_stages: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    region: Mapped[str | None] = mapped_column(String(64))
    # A different document can supersede an older one (e.g. a new version of a
    # standard published under a new code).  Same-document updates use
    # KbDocumentVersion instead.
    supersedes_document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    superseded_by_document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # verified | pending | rejected.  Legacy manual uploads default to verified;
    # collector-imported material is written as pending and must be promoted.
    # Two *separate* review axes.  Technical review is about provenance and
    # parsing and may be automated; domain review is about aquaculture facts and
    # may only be recorded by a human domain reviewer.  Automated checks must
    # never write ``domain_review_status``.
    technical_review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    domain_review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    review_flags: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="verified", server_default="verified"
    )

    __table_args__ = (
        Index("ix_kb_documents_status", "status"),
        Index("ix_kb_documents_source_type", "source_type"),
        Index("ix_kb_documents_authority", "authority_level"),
    )


class KbDocumentVersion(Base, TimestampMixin):
    __tablename__ = "kb_document_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    parser_name: Mapped[str] = mapped_column(String(64), nullable=False, default="pymupdf")
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    chunk_config_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_version_no"),
        Index("ix_versions_document", "document_id", "status"),
        Index("ix_versions_hash", "content_hash"),
    )


class IndexManifest(Base, TimestampMixin):
    """Reproducibility record for a physical Qdrant collection.

    This is deliberately separate from document versions: a collection can
    contain multiple document versions, but it must use one embedding model,
    vector size, and chunking configuration.
    """

    __tablename__ = "index_manifests"

    collection: Mapped[str] = mapped_column(String(128), primary_key=True)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    vector_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_config_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # Hash of the BM25 tokenizer config (jieba version + custom terms +
    # stopwords + index hashing).  Dense-only manifests predate it, so the
    # column defaults to '' instead of NULL.
    bm25_config_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="building")
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class KbChunk(Base, TimestampMixin):
    __tablename__ = "kb_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("kb_document_versions.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    chunk_role: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context_text: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    block_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    page_from: Mapped[int] = mapped_column(Integer, nullable=False)
    page_to: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locations: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_role", "ordinal", name="uq_chunk_ordinal"),
        Index("ix_chunks_version", "document_version_id"),
        Index("ix_chunks_parent", "parent_id"),
    )


class KbIngestJob(Base, TimestampMixin):
    __tablename__ = "kb_ingest_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("kb_document_versions.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(20), nullable=False, default="ingest")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    arq_job_id: Mapped[str | None] = mapped_column(String(128))
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_jobs_version", "document_version_id"),)


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="新会话")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_messages_session", "session_id", "created_at"),)


class ChatCitation(Base, TimestampMixin):
    __tablename__ = "chat_citations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    source_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Nullable because a verified-FAQ citation has no document/version of its
    # own; ``source_type`` says which branch produced the evidence.
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="document", server_default="document"
    )
    faq_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("faq_entries.id", ondelete="SET NULL")
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[dict | list | None] = mapped_column(JSONB)
    score: Mapped[float | None] = mapped_column(Float)
    support_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unverified")
    support_score: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("message_id", "source_index", name="uq_citation_source"),
        Index("ix_citations_version", "document_version_id"),
        Index("ix_citations_faq", "faq_id"),
    )


class QueryLog(Base, TimestampMixin):
    __tablename__ = "query_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_question: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str] = mapped_column(String(20), nullable=False, default="rag")
    retrieval_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    active_versions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    timings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    token_usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    retrieval_rankings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    llm_model: Mapped[str | None] = mapped_column(String(64))
    generation_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    citation_check: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class GraphEntity(Base, TimestampMixin):
    __tablename__ = "graph_entities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="verified")

    __table_args__ = (Index("ix_graph_entities_type", "entity_type"),)


class GraphAlias(Base, TimestampMixin):
    __tablename__ = "graph_aliases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="verified")

    __table_args__ = (Index("ix_graph_aliases_entity", "entity_id"),)


class GraphRelation(Base, TimestampMixin):
    __tablename__ = "graph_relations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance_document_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="verified")

    __table_args__ = (
        UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            name="uq_graph_relation",
        ),
        Index("ix_graph_relations_source", "source_entity_id"),
        Index("ix_graph_relations_target", "target_entity_id"),
    )


class KbChunkEntity(Base):
    __tablename__ = "kb_chunk_entities"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("kb_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("graph_entities.id", ondelete="CASCADE"), primary_key=True
    )
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (Index("ix_chunk_entities_entity", "entity_id"),)


class FaqEntry(Base, TimestampMixin):
    """A curated question/answer pair with a traceable evidence chain.

    A FAQ is *not* a document chunk: it has no page or bbox.  Its citations
    point at ``supporting`` chunks, so an answer can still be traced to the
    original standard.  Only ``review_status="verified"`` rows are indexed into
    Qdrant, which is what keeps unreviewed model output out of retrieval.
    """

    __tablename__ = "faq_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # Normalised question used for exact-duplicate detection and clustering.
    question_norm: Mapped[str] = mapped_column(Text, nullable=False)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    species: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    topic: Mapped[str | None] = mapped_column(String(64))
    growth_stages: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    region: Mapped[str | None] = mapped_column(String(64))

    source_dataset: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Strongest authority level of the supporting documents (derived, stored for
    # cheap filtering); never set by the importer to something stronger.
    source_authority: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    original_id: Mapped[str | None] = mapped_column(String(128))
    original_source_url: Mapped[str | None] = mapped_column(Text)
    source_license: Mapped[str | None] = mapped_column(String(64))
    # Original model/web answer is kept for provenance but is never the answer
    # that gets served: ``answer`` above is the reviewed text.
    original_answer: Mapped[str | None] = mapped_column(Text)

    # [{document_id, version_id, chunk_id, page, quote, score, title}]
    supporting: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none"
    )  # none | partial | supported | conflict
    quality_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    cluster_id: Mapped[str | None] = mapped_column(String(64))

    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )  # pending | verified | rejected
    usage_scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="knowledge", server_default="knowledge"
    )  # knowledge | dev | eval
    confidence: Mapped[float | None] = mapped_column(Float)
    review_notes: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    index_collection: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        UniqueConstraint("question_hash", name="uq_faq_question_hash"),
        Index("ix_faq_review_status", "review_status"),
        Index("ix_faq_topic", "topic"),
        Index("ix_faq_cluster", "cluster_id"),
        Index("ix_faq_scope", "usage_scope"),
    )


class DataRun(Base, TimestampMixin):
    """Audit record for a collection / import run.

    Kept in PostgreSQL (not only in logs) so the thesis can report exactly
    which URLs were fetched, which were blocked by robots, and how many rows a
    FAQ import produced.
    """

    __tablename__ = "data_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # crawl | faq_import | index
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_data_runs_kind", "kind", "created_at"),)


class AppSetting(Base):
    """Small key/value store for runtime-tunable settings (e.g. LLM model)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
