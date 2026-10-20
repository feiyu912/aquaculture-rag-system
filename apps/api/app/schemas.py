from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RetrievalMode = Literal["dense", "bm25", "hybrid", "hybrid_rerank"]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: uuid.UUID | None = None
    category: str | None = None
    species: str | None = None
    retrieval_mode: RetrievalMode = "hybrid"


class VersionOut(BaseModel):
    id: uuid.UUID
    version_no: int
    status: str
    page_count: int
    content_hash: str
    error_message: str | None = None
    created_at: datetime
    activated_at: datetime | None = None


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    species: list[str] = Field(default_factory=list)
    status: str
    current_version_id: uuid.UUID | None = None
    current_version_no: int | None = None
    page_count: int | None = None
    created_at: datetime
    source_org: str | None = None
    source_url: str | None = None
    publish_year: int | None = None
    document_status: str | None = None
    region: str | None = None


class DocumentDetail(DocumentOut):
    versions: list[VersionOut] = Field(default_factory=list)


class JobOut(BaseModel):
    id: uuid.UUID
    document_version_id: uuid.UUID
    status: str
    progress: int
    current_stage: str
    error_code: str | None = None
    error_message: str | None = None
    metrics: dict = Field(default_factory=dict)


class CitationOut(BaseModel):
    id: uuid.UUID
    source_index: int
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_id: uuid.UUID | None = None
    quote: str
    page: int | None = None
    # Stored as the full location record for old rows; ``location`` is the
    # canonical object and ``bbox`` remains for backward compatibility.
    bbox: dict | list | None = None
    location: dict | None = None
    score: float | None = None
    support_status: str
    support_score: float | None = None
    # Denormalised display fields. Optional so older rows / older clients keep
    # working; the web client uses them to label historical citations.
    title: str | None = None
    version_no: int | None = None
    species: list[str] = Field(default_factory=list)


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    status: str
    created_at: datetime
    citations: list[CitationOut] = Field(default_factory=list)
    model: str | None = None
    latency_ms: int | None = None
    meta: dict = Field(default_factory=dict)


class SessionOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    last_message_at: datetime | None = None


class RollbackRequest(BaseModel):
    version_id: uuid.UUID


class CitationVerifyRequest(BaseModel):
    claim: str = Field(min_length=1, max_length=2000)


class SupportOut(BaseModel):
    citation_id: uuid.UUID
    status: str
    score: float
    method: str
    matched_terms: list[str]


class ClaimCheckOut(BaseModel):
    claim: str
    cited_indices: list[int]
    status: str
    score: float
    method: str
    matched_terms: list[str]


class ClaimVerificationOut(BaseModel):
    message_id: uuid.UUID
    summary: dict
    claims: list[ClaimCheckOut]


class UploadResponse(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    job_id: uuid.UUID
    status: str


class DocumentCitationOut(CitationOut):
    """A citation that points at a document, plus the answer it came from."""

    message_id: uuid.UUID
    session_id: uuid.UUID
    question: str
    answer_preview: str
    cited_at: datetime
