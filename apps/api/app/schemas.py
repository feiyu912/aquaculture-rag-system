from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: uuid.UUID | None = None
    category: str | None = None


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
    source_index: int
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    quote: str
    page: int | None = None
    bbox: dict | list | None = None
    score: float | None = None
    support_status: str


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


class UploadResponse(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    job_id: uuid.UUID
    status: str
