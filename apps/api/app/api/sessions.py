from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.generation.claims import summarize_claims, verify_claims
from app.generation.support import verify_support
from app.media import citation_locations, max_location_page, normalize_media_type
from app.models import (
    ChatCitation,
    ChatMessage,
    ChatSession,
    FaqEntry,
    KbDocument,
    KbDocumentVersion,
)
from app.schemas import (
    CitationOut,
    CitationVerifyRequest,
    ClaimVerificationOut,
    MessageOut,
    SessionOut,
    SupportOut,
)
from app.species import normalize_species_list

router = APIRouter(prefix="/api", tags=["sessions"])


def _session_out(session: ChatSession) -> SessionOut:
    return SessionOut(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        last_message_at=session.last_message_at,
    )


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(db: AsyncSession = Depends(get_db)) -> SessionOut:
    session = ChatSession(title="新会话")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _session_out(session)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(db: AsyncSession = Depends(get_db)) -> list[SessionOut]:
    sessions = (
        (await db.execute(select(ChatSession).order_by(ChatSession.updated_at.desc()).limit(100)))
        .scalars()
        .all()
    )
    return [_session_out(session) for session in sessions]


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[MessageOut]:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    message_ids = [message.id for message in messages]
    citations = (
        (
            await db.execute(
                select(ChatCitation)
                .where(ChatCitation.message_id.in_(message_ids))
                .order_by(ChatCitation.source_index.asc())
            )
        )
        .scalars()
        .all()
        if message_ids
        else []
    )
    by_message: dict[uuid.UUID, list[CitationOut]] = {}
    # Display metadata for historical citations: the citation row only stores
    # ids, so titles/species/versions are resolved with one extra query.
    cited_document_ids = {c.document_id for c in citations if c.document_id}
    cited_version_ids = {c.document_version_id for c in citations if c.document_version_id}
    cited_documents = (
        (await db.execute(select(KbDocument).where(KbDocument.id.in_(cited_document_ids))))
        .scalars()
        .all()
        if cited_document_ids
        else []
    )
    cited_versions = (
        (
            await db.execute(
                select(KbDocumentVersion).where(KbDocumentVersion.id.in_(cited_version_ids))
            )
        )
        .scalars()
        .all()
        if cited_version_ids
        else []
    )
    doc_titles = {doc.id: doc.title for doc in cited_documents}
    species_by_document = {doc.id: normalize_species_list(doc.species) for doc in cited_documents}
    version_numbers = {version.id: version.version_no for version in cited_versions}
    documents_by_id = {doc.id: doc for doc in cited_documents}
    versions_by_id = {version.id: version for version in cited_versions}

    cited_faq_ids = {c.faq_id for c in citations if c.faq_id}
    cited_faqs = (
        (await db.execute(select(FaqEntry).where(FaqEntry.id.in_(cited_faq_ids)))).scalars().all()
        if cited_faq_ids
        else []
    )
    faq_by_id = {entry.id: entry for entry in cited_faqs}
    support_version_ids: set[uuid.UUID] = set()
    for entry in cited_faqs:
        for item in entry.supporting or []:
            if not isinstance(item, dict) or not item.get("version_id"):
                continue
            try:
                support_version_ids.add(uuid.UUID(str(item["version_id"])))
            except (TypeError, ValueError):
                continue
    support_versions = (
        (
            await db.execute(
                select(KbDocumentVersion).where(KbDocumentVersion.id.in_(support_version_ids))
            )
        )
        .scalars()
        .all()
        if support_version_ids
        else []
    )
    support_doc_ids = {version.document_id for version in support_versions}
    support_docs = (
        (await db.execute(select(KbDocument).where(KbDocument.id.in_(support_doc_ids))))
        .scalars()
        .all()
        if support_doc_ids
        else []
    )
    support_docs_by_id = {doc.id: doc for doc in support_docs}
    active_support_ids: set[uuid.UUID] = set()
    for version in support_versions:
        support_doc = support_docs_by_id.get(version.document_id)
        if (
            support_doc is not None
            and support_doc.status == "active"
            and support_doc.verification_status == "verified"
            and support_doc.current_version_id == version.id
        ):
            active_support_ids.add(version.id)

    def faq_support_available(entry: FaqEntry) -> bool:
        ids = []
        for item in entry.supporting or []:
            if not isinstance(item, dict) or not item.get("version_id"):
                continue
            try:
                ids.append(uuid.UUID(str(item["version_id"])))
            except (TypeError, ValueError):
                continue
        # A FAQ may list several supports; verification and retrieval accept it
        # when at least one still-active version exists.  Requiring all would
        # report a valid citation as broken after an unrelated version changes.
        return bool(ids) and any(version_id in active_support_ids for version_id in ids)

    for citation in citations:
        source_type = getattr(citation, "source_type", "document") or "document"
        title = doc_titles.get(citation.document_id)
        version_no = version_numbers.get(citation.document_version_id)
        species = species_by_document.get(citation.document_id, [])
        media_type = "pdf"
        source_url = None
        document_status = None
        available = True
        unavailable_reason = None
        if source_type == "faq":
            faq = faq_by_id.get(citation.faq_id) if citation.faq_id else None
            media_type = "faq"
            if faq is None:
                title = "FAQ 已失效"
                available = False
                unavailable_reason = "faq_missing"
            else:
                title = f"FAQ：{faq.question}"
                species = normalize_species_list(faq.species)
                source_url = faq.original_source_url
                if faq.review_status != "verified":
                    available = False
                    unavailable_reason = "faq_not_verified"
                elif not faq_support_available(faq):
                    available = False
                    unavailable_reason = "faq_support_invalid"
        else:
            doc = documents_by_id.get(citation.document_id)
            if doc is not None:
                media_type = normalize_media_type(doc.source_type)
                source_url = doc.source_url
                document_status = doc.status
                if doc.status == "deleted":
                    available = False
                    unavailable_reason = "document_deleted"
            else:
                available = False
                unavailable_reason = "document_missing"
            if citation.document_version_id and citation.document_version_id not in versions_by_id:
                available = False
                unavailable_reason = unavailable_reason or "version_missing"
            if title is None:
                title = "来源文档不存在" if doc is None else doc.title
        is_pdf = media_type == "pdf"
        locations = [] if source_type == "faq" else citation_locations(citation.bbox, media_type)
        location = locations[0] if locations else None
        page = citation.page if is_pdf else None
        if is_pdf and page is None and isinstance(location, dict):
            page = location.get("page") if isinstance(location.get("page"), int) else None
        page_end = max_location_page(locations) if is_pdf else None
        if is_pdf and page_end is None:
            page_end = page
        first_bbox = (
            location.get("bbox")
            if is_pdf and isinstance(location, dict)
            else None
        )
        by_message.setdefault(citation.message_id, []).append(
            CitationOut(
                id=citation.id,
                source_index=citation.source_index,
                document_id=citation.document_id,
                document_version_id=citation.document_version_id,
                source_type=source_type,
                media_type=media_type,
                faq_id=citation.faq_id,
                chunk_id=citation.chunk_id,
                quote=citation.quote,
                page=page,
                page_end=page_end,
                bbox=first_bbox,
                location=location,
                locations=locations,
                score=citation.score,
                support_status=citation.support_status,
                support_score=citation.support_score,
                title=title,
                version_no=version_no,
                species=species,
                source_url=source_url,
                document_status=document_status,
                available=available,
                unavailable_reason=unavailable_reason,
            )
        )
    return [
        MessageOut(
            id=message.id,
            role=message.role,
            content=message.content,
            status=message.status,
            created_at=message.created_at,
            citations=by_message.get(message.id, []),
            model=message.model,
            latency_ms=message.latency_ms,
            meta=message.meta or {},
        )
        for message in messages
    ]


@router.post("/citations/{citation_id}/verify", response_model=SupportOut)
async def verify_citation(
    citation_id: uuid.UUID,
    payload: CitationVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> SupportOut:
    citation = await db.get(ChatCitation, citation_id)
    if citation is None:
        raise HTTPException(status_code=404, detail="引用不存在")
    result = verify_support(payload.claim, citation.quote)
    citation.support_status = result.status
    citation.support_score = result.score
    await db.commit()
    return SupportOut(
        citation_id=citation.id,
        status=result.status,
        score=result.score,
        method=result.method,
        matched_terms=result.matched_terms,
    )


@router.post("/messages/{message_id}/verify-claims", response_model=ClaimVerificationOut)
async def verify_message_claims(
    message_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ClaimVerificationOut:
    message = await db.get(ChatMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    citations = (
        (
            await db.execute(
                select(ChatCitation)
                .where(ChatCitation.message_id == message_id)
                .order_by(ChatCitation.source_index.asc())
            )
        )
        .scalars()
        .all()
    )
    evidence = [{"index": item.source_index, "quote": item.quote} for item in citations]
    claims = verify_claims(message.content, evidence)
    return ClaimVerificationOut(
        message_id=message_id,
        summary=summarize_claims(claims),
        claims=claims,
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.delete(session)
    await db.commit()


def touch_session(session: ChatSession) -> None:
    session.last_message_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
