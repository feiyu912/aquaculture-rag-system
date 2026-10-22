from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RetrievalMode = Literal["dense", "bm25", "hybrid", "hybrid_rerank"]


AnswerMode = Literal["document_rag", "document_faq_rag", "faq_direct"]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: uuid.UUID | None = None
    category: str | None = None
    species: str | None = None
    retrieval_mode: RetrievalMode = "hybrid"
    # document_rag      documents only (default, unchanged behaviour)
    # document_faq_rag  documents first, verified FAQ as a gap-filler
    # faq_direct        answer from one verified FAQ, only under strict guards
    answer_mode: AnswerMode = "document_rag"


class LlmModelUpdate(BaseModel):
    model: str = Field(min_length=0, max_length=128)
    ping: bool = True


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
    # Provenance / trust fields.  ``pending`` documents are staged and are not
    # reachable by retrieval until promoted.
    source_type: str = "pdf"
    authority_level: str = "unknown"
    verification_status: str = "verified"
    # technical = provenance/parsing (may be automated); domain = aquaculture
    # correctness (human domain reviewer only).
    technical_review_status: str = "pending"
    domain_review_status: str = "pending"
    review_flags: list[str] = Field(default_factory=list)
    effective_date: str | None = None
    fetched_at: datetime | None = None


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
    # FAQ citations have no document/version, so both are optional.
    document_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
    source_type: str = "document"
    # pdf | html | faq.  A FAQ row has no page/bbox; an HTML row has no PDF
    # bbox either, so clients must branch on this instead of assuming a PDF.
    media_type: str = "pdf"
    faq_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    quote: str
    page: int | None = None
    page_end: int | None = None
    # Stored as the full location record for old rows; ``location`` is the
    # canonical object and ``bbox`` remains for backward compatibility.
    bbox: dict | list | None = None
    location: dict | None = None
    # Every page/bbox of a PDF parent block.  A single ``bbox`` is only the
    # first location and must not be presented as the whole citation.
    locations: list[dict] = Field(default_factory=list)
    score: float | None = None
    support_status: str
    support_score: float | None = None
    # Denormalised display fields. Optional so older rows / older clients keep
    # working; the web client uses them to label historical citations.
    title: str | None = None
    version_no: int | None = None
    species: list[str] = Field(default_factory=list)
    # Provenance and availability for historical citations.  A deleted
    # document or a superseded FAQ support must be shown as unavailable, not
    # silently opened against a newer version.
    source_url: str | None = None
    document_status: str | None = None
    available: bool = True
    unavailable_reason: str | None = None


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
