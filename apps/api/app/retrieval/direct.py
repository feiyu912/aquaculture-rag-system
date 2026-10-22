"""Verified-FAQ direct answer.

`faq_direct` is deliberately hard to satisfy.  A FAQ may answer without any
document evidence only when **all** of the following hold:

1. the FAQ was human-verified and its supporting versions are still active;
2. it ranks first on *both* dense and BM25 (a vector-only match is exactly the
   "semantically similar but unverified" failure the policy forbids);
3. species / stage / region do not contradict the question;
4. for strict topics the support is a binding or official source;
5. the answer is not conditional ("如果…""视情况…"), because those sentences
   cannot be served without the surrounding context.

Anything else returns ``None`` and the caller falls back to the normal RAG flow
with a recorded ``fallback_reason`` — never to a relaxed threshold.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass

from app.config import settings
from app.retrieval.faq_store import search_faq
from app.retrieval.vector_store import get_client
from app.trust import (
    LEVEL_L2,
    PENDING,
    STRICT_AUTHORITIES,
    TrustProfile,
    applicability_conflict,
    evidence_eligible,
    is_strict_question,
)

CONDITIONAL_MARKERS = ("如果", "若", "视情况", "根据实际", "分情况", "取决于", "必要时")
MIN_ANSWER_CHARS = 12


@dataclass(slots=True)
class DirectAnswer:
    faq_id: uuid.UUID
    question: str
    answer: str
    authority: str
    publisher: str | None
    source_url: str | None
    supporting_document_ids: list[str]
    score: float

    def as_source(self) -> dict:
        return {
            "source_id": "S1",
            "index": 1,
            "source_type": "faq",
            "evidence_level": LEVEL_L2,
            "authority": self.authority,
            "verification_status": "verified",
            "publisher": self.publisher,
            "source_url": self.source_url,
            "supplemental": False,
            "direct_answer": True,
            "faq_id": str(self.faq_id),
            "document_id": (self.supporting_document_ids or [None])[0],
            "version_id": None,
            "chunk_id": None,
            "child_chunk_id": None,
            "title": f"FAQ：{self.question[:60]}",
            "page": None,
            "quote": self.answer[:260],
            "heading_path": [],
            "location": {"coordinate_system": "faq", "faq_id": str(self.faq_id)},
            "bbox": None,
        }


def _fallback(reason: str, **extra) -> dict:
    return {"used": False, "fallback_reason": reason, **extra}


async def try_faq_direct(
    question: str,
    query_ir,
    embedder,
    bm25,
    active_versions: list[uuid.UUID],
) -> tuple[DirectAnswer | None, dict]:
    if not (settings.enable_faq_retrieval and settings.enable_faq_direct_answer):
        return None, _fallback("faq_direct_disabled")

    context = {
        "species": list(getattr(query_ir, "species", []) or []),
        "growth_stages": list(getattr(query_ir, "growth_stage", []) or []),
        "region": getattr(query_ir, "region", None),
    }
    strict = is_strict_question(question)

    dense = await asyncio.to_thread(embedder.embed_query, question)
    sparse = bm25.query_vector(question)
    client = get_client()
    try:
        hits = await asyncio.to_thread(
            search_faq, client, dense, sparse, top_k=max(4, settings.faq_supplement_k * 2)
        )
    except Exception as exc:  # noqa: BLE001
        return None, _fallback("faq_search_failed", error=str(exc)[:160])
    finally:
        client.close()

    if not hits:
        return None, _fallback("no_faq_match")

    top = hits[0]
    if not (top.get("dense_rank") == 1 and top.get("sparse_rank") == 1):
        return None, _fallback("not_top1_on_both_retrievers")

    payload = top["payload"]
    profile = TrustProfile(
        level=payload.get("evidence_level") or LEVEL_L2,
        authority=payload.get("source_authority") or "unknown",
        verification_status=payload.get("verification_status") or PENDING,
        publisher=payload.get("publisher"),
        source_url=payload.get("source_url"),
        applicability={
            "species": payload.get("species") or [],
            "growth_stages": payload.get("growth_stages") or [],
            "region": payload.get("region"),
        },
    )
    ok, reason = evidence_eligible(profile, strict=strict)
    if not ok:
        return None, _fallback(reason)

    conflict, why = applicability_conflict(profile.applicability, context)
    if conflict:
        return None, _fallback(why)

    support = [str(v) for v in (payload.get("supporting_version_ids") or [])]
    active = {str(v) for v in active_versions}
    if not support or not (set(support) & active):
        return None, _fallback("support_not_active")

    answer = (payload.get("answer") or "").strip()
    if len(answer) < MIN_ANSWER_CHARS:
        return None, _fallback("answer_too_short")
    if any(marker in answer for marker in CONDITIONAL_MARKERS):
        return None, _fallback("answer_is_conditional")
    if strict and profile.authority not in STRICT_AUTHORITIES:
        return None, _fallback("strict_topic_requires_authoritative_source")

    faq_id = payload.get("faq_id") or payload.get("chunk_id")
    try:
        faq_uuid = uuid.UUID(str(faq_id))
    except (ValueError, TypeError):
        return None, _fallback("invalid_faq_id")

    return (
        DirectAnswer(
            faq_id=faq_uuid,
            question=payload.get("question") or question,
            answer=answer,
            authority=profile.authority,
            publisher=profile.publisher,
            source_url=profile.source_url,
            supporting_document_ids=[
                str(v) for v in (payload.get("supporting_document_ids") or []) if v
            ],
            score=float(top["score"]),
        ),
        {"used": True, "faq_id": str(faq_uuid), "score": round(float(top["score"]), 6)},
    )
