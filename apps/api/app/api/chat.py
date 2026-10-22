from __future__ import annotations

import asyncio
import json
import logging
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
from app.generation.context import context_budget, finalize_evidence
from app.generation.llm import Generator, LLMError, MockGenerator, build_generator
from app.generation.semantic_claims import verify_claims_semantic
from app.ingestion.embedder import get_embedder
from app.models import ChatCitation, ChatMessage, ChatSession, KbDocument, QueryLog
from app.query.planner import planner_from_generator
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.direct import try_faq_direct
from app.retrieval.rerank import build_reranker
from app.retrieval.service import Evidence, RetrievalResult, retrieve
from app.runtime_settings import (
    LLM_MODEL_KEY,
    apply_llm_override,
    env_llm_model,
    get_setting,
)
from app.schemas import ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])

logger = logging.getLogger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _llm_model_name() -> str:
    return env_llm_model(settings)


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

    answer_mode = payload.answer_mode
    if answer_mode != "document_rag" and not settings.enable_faq_retrieval:
        raise HTTPException(status_code=400, detail="FAQ 检索未启用，answer_mode 仅支持 document_rag")
    if answer_mode == "faq_direct" and not settings.enable_faq_direct_answer:
        raise HTTPException(status_code=400, detail="FAQ 直答未启用")

    started = time.perf_counter()
    request_id = uuid.uuid4().hex

    llm_override = await get_setting(db, LLM_MODEL_KEY)
    model_name = llm_override or _llm_model_name()
    generator_config = apply_llm_override(settings, llm_override)

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
        model=model_name,
        meta={"request_id": request_id},
    )
    db.add_all([user_message, assistant_message])
    touch_session(session)
    await db.commit()
    session_id = session.id
    assistant_id = assistant_message.id

    try:
        embedder = get_embedder(
            settings.embedding_model,
            settings.qdrant_vector_size,
            settings.embedding_device,
            settings.embedding_use_fp16,
            settings.embedding_batch_size,
            settings.embedding_max_length,
        )
        bm25 = BM25SparseEncoder(
            k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len
        )
        reranker = (
            build_reranker(
                settings.reranker_model,
                path=settings.reranker_path or None,
                device=settings.reranker_device,
                use_fp16=settings.reranker_use_fp16,
            )
            if payload.retrieval_mode == "hybrid_rerank"
            else None
        )
        planner = None
        planner_generator = None
        if settings.enable_llm_planner:
            try:
                planner_generator = build_generator(generator_config)
                planner = planner_from_generator(planner_generator)
            except LLMError:
                # The planner is optional; missing configuration falls back to
                # the rule IR.  The generation leg will still fail explicitly.
                planner_generator = None
        retrieval: RetrievalResult = await retrieve(
            db,
            question,
            embedder,
            bm25,
            reranker=reranker,
            planner=planner,
            category=payload.category,
            species=payload.species,
            mode=payload.retrieval_mode,
            include_faq=answer_mode != "document_rag",
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

    # Retrieval already budgets documents at MAX_SOURCES and appends at most
    # FAQ_SUPPLEMENT_K verified FAQ items.  Do not truncate to MAX_SOURCES here:
    # that would drop the FAQ evidence the sufficiency gate just counted.  The
    # same returned list is used for the gate result, the sources event,
    # generation and citation persistence.
    evidence: list[Evidence] = finalize_evidence(
        list(retrieval.evidence),
        document_slots=settings.max_sources,
        faq_slots=settings.faq_supplement_k,
    )
    faq_direct_trace: dict | None = None
    answer_mode_used = "document_rag" if answer_mode == "document_rag" else "document_faq_rag"
    if answer_mode == "faq_direct":
        if retrieval.sufficient:
            # Documents already answer it: never prefer a FAQ over an original.
            faq_direct_trace = {"used": False, "fallback_reason": "documents_sufficient"}
        else:
            direct, faq_direct_trace = await try_faq_direct(
                question,
                retrieval.query_ir,
                embedder,
                bm25,
                retrieval.active_versions,
            )
            if direct is not None:
                evidence = [
                    Evidence(
                        source_index=1,
                        document_id=None,
                        version_id=None,
                        parent_chunk_id=None,
                        child_chunk_id=None,
                        title=f"FAQ：{direct.question[:60]}",
                        version_no=0,
                        page=None,
                        quote=direct.answer[:260],
                        content=direct.answer,
                        location={"coordinate_system": "faq", "faq_id": str(direct.faq_id)},
                        score=direct.score,
                        species=[],
                        heading_path=[],
                        source_type="faq",
                        media_type="faq",
                        faq_id=direct.faq_id,
                        evidence_level="L2_verified_faq",
                        authority=direct.authority,
                        verification_status="verified",
                        publisher=direct.publisher,
                        source_url=direct.source_url,
                        supplemental=False,
                    )
                ]
                retrieval.sufficient = True
                retrieval.gate = {"sufficient": True, "reason": "faq_direct"}
                answer_mode_used = "faq_direct"

    evidence_budget = context_budget(
        evidence,
        document_slots=settings.max_sources,
        faq_slots=settings.faq_supplement_k,
    )

    try:
        generator: Generator = planner_generator or (
            build_generator(generator_config)
            if evidence or settings.llm_provider != "deepseek"
            else MockGenerator()
        )
    except LLMError as exc:
        await _persist_failure(
            assistant_id,
            request_id,
            question,
            "",
            f"generation_unavailable: {exc}",
            started,
            session_id,
        )
        raise HTTPException(status_code=503, detail="生成服务未配置或不可用") from exc

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
                "adaptive_route": retrieval.config.get("adaptive_route"),
                "targeted_retrieval": retrieval.config.get("targeted_retrieval"),
                "graph_expansion": retrieval.config.get("graph_expansion"),
                "llm_planner": retrieval.config.get("llm_planner"),
                "gate": retrieval.gate,
                "answer_mode": answer_mode,
                "answer_mode_used": answer_mode_used,
                "faq_supplement": retrieval.config.get("faq_supplement"),
                "faq_direct": faq_direct_trace,
                "applicability_filter": retrieval.config.get("applicability_filter"),
                "strict_source_filter": retrieval.config.get("strict_source_filter"),
                "context_budget": evidence_budget,
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

        if not answer.strip():
            await _persist_failure(
                assistant_id,
                request_id,
                question,
                answer,
                "empty_generation",
                started,
                session_id,
                retrieval,
            )
            yield _sse(
                "error",
                {
                    "code": "empty_generation",
                    "message": "模型没有返回可见文本；请检查 max_tokens、推理预算或服务配置。",
                    "retryable": True,
                },
            )
            return

        citation_report = validate_answer(answer, len(evidence))
        report = citation_report.as_dict()
        if settings.enable_claim_verification:
            sources = [item.as_source() for item in evidence]
            if settings.enable_semantic_claims:
                claims = verify_claims_semantic(
                    answer,
                    sources,
                    embedder,
                    threshold=settings.semantic_claim_threshold,
                )
            else:
                claims = verify_claims(answer, sources)
            report["claims"] = claims
            report["claim_summary"] = summarize_claims(claims)
            if settings.enable_semantic_claims:
                report["claim_summary"]["method"] = "lexical_overlap_v0+bge_m3_cosine_v0"
                report["claim_summary"]["semantic_threshold"] = settings.semantic_claim_threshold
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
            model=model_name,
            cost_usd=cost_usd,
        )
        yield _sse(
            "done",
            {
                "message_id": str(assistant_id),
                "model": model_name,
                "usage": generator.last_usage,
                "cost_usd": cost_usd,
                "timings": timings,
                "retrieval_mode": retrieval.config.get("retrieval_mode"),
                "query_ir": retrieval.config.get("query_ir"),
                "adaptive_route": retrieval.config.get("adaptive_route"),
                "targeted_retrieval": retrieval.config.get("targeted_retrieval"),
                "graph_expansion": retrieval.config.get("graph_expansion"),
                "llm_planner": retrieval.config.get("llm_planner"),
                "sufficient": retrieval.sufficient,
                "gate": retrieval.gate,
                "citation_check": report,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


def _estimate_cost(usage: dict, model: str) -> float:
    if model == "deepseek":
        input_price = settings.deepseek_price_input_per_m
        output_price = settings.deepseek_price_output_per_m
    elif model in {"openai_compatible", "openai"}:
        input_price = settings.openai_price_input_per_m
        output_price = settings.openai_price_output_per_m
    else:
        return 0.0
    prompt = float(usage.get("prompt_tokens") or 0)
    completion = float(usage.get("completion_tokens") or 0)
    return round(prompt / 1_000_000 * input_price + completion / 1_000_000 * output_price, 6)


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
            "adaptive_route": retrieval.config.get("adaptive_route"),
            "targeted_retrieval": retrieval.config.get("targeted_retrieval"),
            "graph_expansion": retrieval.config.get("graph_expansion"),
        }
        for item in evidence:
            stored_location = dict(item.location) if isinstance(item.location, dict) else None
            if item.locations:
                stored_location = {**(stored_location or {}), "locations": item.locations}
            db.add(
                ChatCitation(
                    message_id=assistant_id,
                    source_index=item.source_index,
                    document_id=item.document_id,
                    document_version_id=item.version_id,
                    chunk_id=item.parent_chunk_id,
                    quote=item.quote,
                    page=item.page,
                    source_type=item.source_type,
                    faq_id=item.faq_id,
                    bbox=stored_location,
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
                route=str(
                    (retrieval.config.get("adaptive_route") if retrieval else None) or "rag"
                ),
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
                    "adaptive_route": retrieval.config.get("adaptive_route"),
                    "adaptive_modules": retrieval.config.get("adaptive_modules"),
                    "targeted_retrieval": retrieval.config.get("targeted_retrieval"),
                    "graph_expansion": retrieval.config.get("graph_expansion"),
                    "llm_planner": retrieval.config.get("llm_planner"),
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
    """Persist a terminal failed state; never mask the original exception."""
    try:
        async with SessionLocal() as db:
            message = await db.get(ChatMessage, assistant_id)
            if message:
                message.content = partial
                message.status = "failed"
                message.meta = {
                    **(message.meta or {}),
                    "request_id": request_id,
                    "error": error[:500],
                }
                message.latency_ms = int((time.perf_counter() - started) * 1000)
            db.add(
                QueryLog(
                    request_id=request_id,
                    session_id=session_id,
                    message_id=assistant_id,
                    question=question,
                    route=str(
                        (retrieval.config.get("adaptive_route") if retrieval else None) or "rag"
                    ),
                    retrieval_config=retrieval.config if retrieval else {},
                    active_versions=(
                        [str(v) for v in retrieval.active_versions] if retrieval else []
                    ),
                    timings={"total_ms": round((time.perf_counter() - started) * 1000, 1)},
                    token_usage={},
                    citation_check={"error": error[:500]},
                )
            )
            await db.commit()
    except Exception:
        logger.exception("could not persist failed state for message %s", assistant_id)
