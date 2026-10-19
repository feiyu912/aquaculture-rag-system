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
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_kb_documents_status", "status"),)


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
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[dict | list | None] = mapped_column(JSONB)
    score: Mapped[float | None] = mapped_column(Float)
    support_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unverified")
    support_score: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("message_id", "source_index", name="uq_citation_source"),
        Index("ix_citations_version", "document_version_id"),
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
