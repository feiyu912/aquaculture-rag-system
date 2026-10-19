from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.generation.support import verify_support
from app.models import ChatCitation, ChatMessage, ChatSession
from app.schemas import CitationOut, CitationVerifyRequest, MessageOut, SessionOut, SupportOut

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
    for citation in citations:
        by_message.setdefault(citation.message_id, []).append(
            CitationOut(
                id=citation.id,
                source_index=citation.source_index,
                document_id=citation.document_id,
                document_version_id=citation.document_version_id,
                quote=citation.quote,
                page=citation.page,
                bbox=citation.bbox,
                score=citation.score,
                support_status=citation.support_status,
                support_score=citation.support_score,
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
