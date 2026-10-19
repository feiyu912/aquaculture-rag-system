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
    quote: str
    page: int | None = None
    bbox: dict | list | None = None
    score: float | None = None
    support_status: str
    support_score: float | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    status: str
    created_at: datetime
    citations: list[CitationOut] = Field(default_factory=list)


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
