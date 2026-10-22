"""Verified-FAQ vector points, isolated inside the existing collection.

Design choice (and the reason for it)
-------------------------------------
A separate Qdrant collection would duplicate client/manifest/snapshot handling
for one extra document class.  Instead FAQ points live in the *same* collection
but are separated by a payload contract that the retrieval layer enforces:

* ``source_type = "faq"``      -> non-document
* ``chunk_role  = "faq"``      -> never matched by document queries, because
                                  ``version_filter`` always pins ``chunk_role``
* ``verification_status``      -> ``verified`` is required by every search

Isolation is therefore structural, not a sorting preference: a document query
filters on ``document_version_id`` (which FAQ points do not have) and an FAQ
query filters on ``source_type="faq"``.  Neither can return the other's points
even if the vectors are nearly identical.

Unverified QA (L3) is **never written here**.  ``upsert_faq`` refuses to index
anything whose review status is not ``verified``; pending candidates stay in
PostgreSQL where they can only be used by offline tooling.
"""

from __future__ import annotations

import uuid

from qdrant_client import QdrantClient, models

from app.config import settings

FAQ_SOURCE_TYPE = "faq"
FAQ_CHUNK_ROLE = "faq"
FAQ_EVIDENCE_LEVEL = "L2_verified_faq"
VERIFIED = "verified"


class UnverifiedFaqError(RuntimeError):
    """Raised when code tries to index a FAQ that a human has not verified."""


def faq_text(question: str, answer: str) -> str:
    return f"问题：{question.strip()}\n答案：{answer.strip()}"


def faq_filter(species: str | None = None) -> models.Filter:
    must: list[models.Condition] = [
        models.FieldCondition(
            key="source_type", match=models.MatchValue(value=FAQ_SOURCE_TYPE)
        ),
        models.FieldCondition(key="chunk_role", match=models.MatchValue(value=FAQ_CHUNK_ROLE)),
        models.FieldCondition(
            key="verification_status", match=models.MatchValue(value=VERIFIED)
        ),
    ]
    should = None
    if species:
        should = [
            models.FieldCondition(
                key="species", match=models.MatchAny(any=[species, "通用"])
            )
        ]
    return models.Filter(must=must, should=should)


def upsert_faq(
    client: QdrantClient,
    faq_id: uuid.UUID,
    payload: dict,
    dense: list[float],
    sparse: models.SparseVector,
) -> None:
    if payload.get("verification_status") != VERIFIED:
        raise UnverifiedFaqError(
            f"refusing to index faq {faq_id}: status={payload.get('verification_status')!r}"
        )
    point_payload = {
        "chunk_id": str(faq_id),
        "faq_id": str(faq_id),
        "source_type": FAQ_SOURCE_TYPE,
        "chunk_role": FAQ_CHUNK_ROLE,
        "evidence_level": FAQ_EVIDENCE_LEVEL,
        "verification_status": VERIFIED,
        **payload,
    }
    client.upsert(
        collection_name=settings.qdrant_collection,
        points=[models.PointStruct(id=str(faq_id), vector={"dense": dense, "bm25": sparse}, payload=point_payload)],
        wait=True,
    )


def delete_faq(client: QdrantClient, faq_id: uuid.UUID) -> None:
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.PointIdsList(points=[str(faq_id)]),
        wait=True,
    )


def _search(
    client: QdrantClient, vector_name: str, vector, top_k: int, species: str | None
) -> list:
    return client.query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        using=vector_name,
        query_filter=faq_filter(species),
        limit=top_k,
        with_payload=True,
    ).points


def search_faq(
    client: QdrantClient,
    dense: list[float],
    sparse: models.SparseVector,
    *,
    top_k: int = 4,
    species: str | None = None,
    rrf_k: int | None = None,
) -> list[dict]:
    """RRF fusion over dense + BM25 restricted to verified FAQ points."""
    k = rrf_k or settings.rrf_k
    dense_hits = _search(client, "dense", dense, top_k, species)
    sparse_hits = _search(client, "bm25", sparse, top_k, species)
    fused: dict[str, dict] = {}
    for rank, hit in enumerate(dense_hits, start=1):
        entry = fused.setdefault(
            str(hit.id), {"payload": hit.payload or {}, "score": 0.0, "dense_rank": rank, "sparse_rank": None}
        )
        entry["score"] += 1.0 / (k + rank)
    for rank, hit in enumerate(sparse_hits, start=1):
        entry = fused.setdefault(
            str(hit.id), {"payload": hit.payload or {}, "score": 0.0, "dense_rank": None, "sparse_rank": rank}
        )
        entry["score"] += 1.0 / (k + rank)
        entry["payload"] = hit.payload or entry["payload"]
        if entry.get("sparse_rank") is None:
            entry["sparse_rank"] = rank
    ordered = sorted(fused.values(), key=lambda item: -item["score"])
    # Only keep items found by both retrievers: a FAQ offered purely on vector
    # similarity is exactly the failure mode the trust policy forbids.
    return [item for item in ordered if item["dense_rank"] and item["sparse_rank"]]