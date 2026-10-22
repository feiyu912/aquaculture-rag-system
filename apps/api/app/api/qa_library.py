"""Read-only browse and similar-question search over the HF QA memory.

Exposed only for the knowledge-management page. The QA memory is a separate
Qdrant collection; nothing here is imported by chat/retrieval/generation, and
the response deliberately omits verification fields so the page cannot read as
"certified FAQ". Answers shown here are for reference and question-structure
inspection; final answers must rest on document evidence.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query
from qdrant_client import models

from app.config import settings
from app.ingestion.embedder import get_embedder
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.vector_store import get_client

router = APIRouter(prefix="/api", tags=["qa-library"])
COLLECTION = "qa_memory_hf_v1"
SUMMARY_TTL = 60.0
_summary_cache: dict = {"at": 0.0, "data": None}


def _base_filter(topic: str | None = None) -> models.Filter:
    must: list[models.Condition] = [
        models.FieldCondition(key="source_type", match=models.MatchValue(value="qa_memory"))
    ]
    if topic:
        must.append(models.FieldCondition(key="topics", match=models.MatchAny(any=[topic])))
    return models.Filter(must=must)


def _to_item(payload: dict, score: float | None = None) -> dict:
    item = {
        "original_id": payload.get("original_id"),
        "question": payload.get("question"),
        "answer": payload.get("answer"),
        "topics": payload.get("topics") or [],
        "species": payload.get("species") or [],
        "dataset_id": payload.get("dataset_id"),
        "license": payload.get("license"),
    }
    if score is not None:
        item["score"] = round(float(score), 6)
    return item


def _require_collection(client):
    if not client.collection_exists(COLLECTION):
        raise HTTPException(status_code=404, detail="问答数据尚未构建")


@router.get("/qa-library/summary")
async def summary():
    cached = _summary_cache
    if cached["data"] and time.time() - cached["at"] < SUMMARY_TTL:
        return cached["data"]
    client = get_client()
    if not client.collection_exists(COLLECTION):
        return {"available": False, "total": 0, "datasets": [], "topics": []}
    total = client.count(collection_name=COLLECTION, exact=True).count
    dataset_counts: dict[str, int] = {}
    topic_counts: dict[str, int] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION,
            limit=1000,
            offset=offset,
            with_payload=["dataset_id", "topics"],
            with_vectors=False,
        )
        for p in points:
            payload = p.payload or {}
            ds = payload.get("dataset_id") or "unknown"
            dataset_counts[ds] = dataset_counts.get(ds, 0) + 1
            for topic in payload.get("topics") or []:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if offset is None:
            break
    data = {
        "available": True,
        "total": total,
        "datasets": [
            {"dataset_id": k, "count": v} for k, v in sorted(dataset_counts.items(), key=lambda kv: -kv[1])
        ],
        "topics": [{"topic": k, "count": v} for k, v in sorted(topic_counts.items(), key=lambda kv: -kv[1])],
    }
    _summary_cache.update({"at": time.time(), "data": data})
    return data


@router.get("/qa-library")
async def list_items(
    q: str | None = Query(default=None, max_length=200),
    topic: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
):
    client = get_client()
    _require_collection(client)
    query = (q or "").strip()

    if query:
        emb = get_embedder(
            settings.embedding_model,
            settings.qdrant_vector_size,
            settings.embedding_device,
            settings.embedding_use_fp16,
            settings.embedding_batch_size,
            settings.embedding_max_length,
        )
        dense = await asyncio.to_thread(emb.embed_query, query)
        bm25 = BM25SparseEncoder(k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len)
        top_k = max(limit + offset, 20)
        dense_hits = client.query_points(
            collection_name=COLLECTION,
            query=dense,
            using="dense",
            query_filter=_base_filter(topic),
            limit=top_k,
            with_payload=True,
        ).points
        sparse_hits = client.query_points(
            collection_name=COLLECTION,
            query=bm25.query_vector(query),
            using="bm25",
            query_filter=_base_filter(topic),
            limit=top_k,
            with_payload=True,
        ).points
        k = settings.rrf_k
        fused: dict[str, dict] = {}
        for rank, hit in enumerate(dense_hits, start=1):
            entry = fused.setdefault(str(hit.id), {"payload": dict(hit.payload or {}), "score": 0.0, "dense": False, "sparse": False})
            entry["score"] += 1.0 / (k + rank)
            entry["dense"] = True
        for rank, hit in enumerate(sparse_hits, start=1):
            entry = fused.setdefault(str(hit.id), {"payload": dict(hit.payload or {}), "score": 0.0, "dense": False, "sparse": False})
            entry["score"] += 1.0 / (k + rank)
            entry["sparse"] = True
        # Both channels must agree, mirroring the verified-FAQ trust policy:
        # a dense-only nearest neighbour is often merely topically adjacent.
        ordered = [v for v in sorted(fused.values(), key=lambda item: -item["score"]) if v["dense"] and v["sparse"]]
        items = [_to_item(entry["payload"], entry["score"]) for entry in ordered[offset : offset + limit]]
        return {"items": items, "total": len(ordered), "limit": limit, "offset": offset}

    # Browse: stable scroll order, numeric paging via slicing.
    points, _ = client.scroll(
        collection_name=COLLECTION,
        limit=offset + limit,
        offset=None,
        scroll_filter=_base_filter(topic),
        with_payload=True,
        with_vectors=False,
    )
    items = [_to_item(p.payload or {}) for p in points[offset : offset + limit]]
    total = client.count(collection_name=COLLECTION, count_filter=_base_filter(topic), exact=True).count
    return {"items": items, "total": total, "limit": limit, "offset": offset}