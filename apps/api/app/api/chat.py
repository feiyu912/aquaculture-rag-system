from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sessions import touch_session
from app.config import settings
from app.db import SessionLocal, get_db
from app.generation.citations import validate_answer
from app.generation.claims import summarize_claims, verify_claims
from app.generation.llm import Generator, MockGenerator, build_generator
from app.ingestion.embedder import get_embedder
from app.models import ChatCitation, ChatMessage, ChatSession, KbDocument, QueryLog
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.rerank import build_reranker
from app.retrieval.service import Evidence, RetrievalResult, retrieve
from app.schemas import ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    started = time.perf_counter()
    request_id = uuid.uuid4().hex

    if payload.session_id:
        session = await db.get(ChatSession, payload.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        session = ChatSession(title=question[:30])
        db.add(session)
        await db.flush()

    user_message = ChatMessage(
        session_id=session.id, role="user", content=question, status="completed"
    )
    assistant_message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content="",
        status="streaming",
        model=settings.llm_provider,
        meta={"request_id": request_id},
    )
    db.add_all([user_message, assistant_message])
    touch_session(session)
    await db.commit()
    session_id = session.id
    assistant_id = assistant_message.id

    embedder = get_embedder(settings.embedding_model, settings.qdrant_vector_size)
    bm25 = BM25SparseEncoder(k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len)
    reranker = (
        build_reranker(settings.reranker_model)
        if payload.retrieval_mode == "hybrid_rerank"
        else None
    )
    try:
        retrieval: RetrievalResult = await retrieve(
            db,
            question,
            embedder,
            bm25,
            reranker=reranker,
            category=payload.category,
            species=payload.species,
            mode=payload.retrieval_mode,
        )
    except Exception as exc:
        await _persist_failure(
            assistant_id,
            request_id,
            question,
            "",
            f"retrieval_failed: {exc}",
            started,
            session_id,
        )
        raise HTTPException(status_code=503, detail="检索服务暂不可用") from exc

    evidence: list[Evidence] = retrieval.evidence[: settings.max_sources]
    for index, item in enumerate(evidence, start=1):
        item.source_index = index

    generator: Generator = (
        build_generator() if evidence or settings.llm_provider != "deepseek" else MockGenerator()
    )

    async def event_stream():
        answer = ""
        first_token_at: float | None = None
        yield _sse(
            "meta",
            {
                "request_id": request_id,
                "session_id": str(session_id),
                "message_id": str(assistant_id),
            },
        )
        yield _sse(
            "status",
            {
                "stage": "retrieved",
                "sources": len(evidence),
                "active_versions": len(retrieval.active_versions),
                "sufficient": retrieval.sufficient,
                "retrieval_mode": retrieval.config.get("retrieval_mode"),
                "species_filter": retrieval.config.get("species_filter"),
                "query_ir": retrieval.config.get("query_ir"),
                "gate": retrieval.gate,
            },
        )
        yield _sse("sources", {"sources": [item.as_source() for item in evidence]})

        try:
            async for token in generator.stream(question, evidence):
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                answer += token
                yield _sse("token", {"text": token})
        except asyncio.CancelledError:
            await _persist_failure(
                assistant_id,
                request_id,
                question,
                answer,
                "client_disconnected",
                started,
                session_id,
                retrieval,
            )
            raise
        except Exception as exc:
            await _persist_failure(
                assistant_id,
                request_id,
                question,
                answer,
                f"generation_failed: {exc}",
                started,
                session_id,
                retrieval,
            )
            yield _sse(
                "error",
                {"code": "generation_failed", "message": str(exc)[:300], "retryable": True},
            )
            return

        citation_report = validate_answer(answer, len(evidence))
        report = citation_report.as_dict()
        if settings.enable_claim_verification:
            claims = verify_claims(answer, [item.as_source() for item in evidence])
            report["claims"] = claims
            report["claim_summary"] = summarize_claims(claims)
        now = time.perf_counter()
        timings = {
            **retrieval.timings,
            "ttft_ms": round((first_token_at - started) * 1000, 1) if first_token_at else None,
            "generation_ms": round((now - (first_token_at or now)) * 1000, 1),
            "total_ms": round((now - started) * 1000, 1),
        }
        cost_usd = _estimate_cost(generator.last_usage, generator.name)
        yield _sse("citation_check", report)
        await _persist_success(
            assistant_id=assistant_id,
            request_id=request_id,
            session_id=session_id,
            question=question,
            answer=answer,
            evidence=evidence,
            retrieval=retrieval,
            report=report,
            timings=timings,
            usage=generator.last_usage,
            model=generator.name,
            cost_usd=cost_usd,
        )
        yield _sse(
            "done",
            {
                "message_id": str(assistant_id),
                "model": generator.name,
                "usage": generator.last_usage,
                "cost_usd": cost_usd,
                "timings": timings,
                "retrieval_mode": retrieval.config.get("retrieval_mode"),
                "query_ir": retrieval.config.get("query_ir"),
                "sufficient": retrieval.sufficient,
                "gate": retrieval.gate,
                "citation_check": report,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


def _estimate_cost(usage: dict, model: str) -> float:
    if model != "deepseek":
        return 0.0
    prompt = float(usage.get("prompt_tokens") or 0)
    completion = float(usage.get("completion_tokens") or 0)
    return round(
        prompt / 1_000_000 * settings.deepseek_price_input_per_m
        + completion / 1_000_000 * settings.deepseek_price_output_per_m,
        6,
    )


async def _persist_success(
    *,
    assistant_id: uuid.UUID,
    request_id: str,
    session_id: uuid.UUID,
    question: str,
    answer: str,
    evidence: list[Evidence],
    retrieval: RetrievalResult,
    report: dict,
    timings: dict,
    usage: dict,
    model: str,
    cost_usd: float,
) -> None:
    async with SessionLocal() as db:
        message = await db.get(ChatMessage, assistant_id)
        if message is None:
            return
        message.content = answer
        message.status = "completed"
        message.model = model
        message.latency_ms = int(timings.get("total_ms") or 0)
        message.prompt_tokens = usage.get("prompt_tokens")
        message.completion_tokens = usage.get("completion_tokens")
        current_versions = (
            (
                await db.execute(
                    select(KbDocument.current_version_id).where(
                        KbDocument.status == "active",
                        KbDocument.current_version_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        superseded = {str(v) for v in current_versions} != {
            str(v) for v in retrieval.active_versions
        }
        message.meta = {
            **(message.meta or {}),
            "request_id": request_id,
            "citation_check": report,
            "evidence_count": len(evidence),
            "superseded": superseded,
        }
        for item in evidence:
            db.add(
                ChatCitation(
                    message_id=assistant_id,
                    source_index=item.source_index,
                    document_id=item.document_id,
                    document_version_id=item.version_id,
                    chunk_id=item.parent_chunk_id,
                    quote=item.quote,
                    page=item.page,
                    bbox=item.location,
                    score=item.score,
                    support_status="unverified",
                    support_score=None,
                )
            )
        db.add(
            QueryLog(
                request_id=request_id,
                session_id=session_id,
                message_id=assistant_id,
                question=question,
                route="rag",
                retrieval_config=retrieval.config,
                active_versions=[str(v) for v in retrieval.active_versions],
                timings=timings,
                token_usage=usage,
                retrieval_rankings=retrieval.rankings,
                evidence=[item.as_source() for item in evidence],
                llm_model=model,
                generation_config={
                    "llm_provider": settings.llm_provider,
                    "temperature": 0.2,
                    "retrieval_mode": retrieval.config.get("retrieval_mode"),
                    "reranker": retrieval.config.get("reranker"),
                },
                cost_usd=cost_usd,
                citation_check=report,
            )
        )
        session = await db.get(ChatSession, session_id)
        if session:
            session.last_message_at = datetime.now(UTC)
        await db.commit()


async def _persist_failure(
    assistant_id: uuid.UUID,
    request_id: str,
    question: str,
    partial: str,
    error: str,
    started: float,
    session_id: uuid.UUID,
    retrieval: RetrievalResult | None = None,
) -> None:
    async with SessionLocal() as db:
        message = await db.get(ChatMessage, assistant_id)
        if message:
            message.content = partial
            message.status = "failed"
            message.meta = {**(message.meta or {}), "request_id": request_id, "error": error[:500]}
            message.latency_ms = int((time.perf_counter() - started) * 1000)
        db.add(
            QueryLog(
                request_id=request_id,
                session_id=session_id,
                message_id=assistant_id,
                question=question,
                route="rag",
                retrieval_config=retrieval.config if retrieval else {},
                active_versions=[str(v) for v in retrieval.active_versions] if retrieval else [],
                timings={"total_ms": round((time.perf_counter() - started) * 1000, 1)},
                token_usage={},
                citation_check={"error": error[:500]},
            )
        )
        await db.commit()
