from __future__ import annotations

import uuid
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from app.config import settings
from app.ingestion.chunker import ChunkDraft
from app.species import GENERAL_SPECIES, normalize_species_list


@dataclass(slots=True)
class SearchHit:
    chunk_id: str
    score: float
    payload: dict


def get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)


def ensure_collection(client: QdrantClient | None = None) -> None:
    client = client or get_client()
    if client.collection_exists(settings.qdrant_collection):
        # Existing dev collections may predate the species filter/index.
        _ensure_payload_indexes(client)
        return
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config={
            "dense": models.VectorParams(
                size=settings.qdrant_vector_size, distance=models.Distance.COSINE
            )
        },
        sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    _ensure_payload_indexes(client)


def _ensure_payload_indexes(client: QdrantClient) -> None:
    info = client.get_collection(settings.qdrant_collection)
    existing = set((info.payload_schema or {}).keys())
    for field in ("document_id", "document_version_id", "category", "chunk_role", "species"):
        if field in existing:
            continue
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name=field,
            field_schema="keyword",
            wait=True,
        )


def version_filter(
    version_ids: list[uuid.UUID | str],
    category: str | None = None,
    chunk_role: str | None = "child",
    species: str | None = None,
) -> models.Filter:
    must: list[models.Condition] = [
        models.FieldCondition(
            key="document_version_id",
            match=models.MatchAny(any=[str(v) for v in version_ids]),
        )
    ]
    if chunk_role:
        must.append(
            models.FieldCondition(key="chunk_role", match=models.MatchValue(value=chunk_role))
        )
    if category:
        must.append(models.FieldCondition(key="category", match=models.MatchValue(value=category)))
    should = None
    if species:
        should = [
            models.FieldCondition(
                key="species",
                match=models.MatchAny(any=[species, GENERAL_SPECIES]),
            )
        ]
    return models.Filter(must=must, should=should)


def upsert_chunks(
    client: QdrantClient,
    chunks: list[ChunkDraft],
    dense_vectors: list[list[float]],
    sparse_vectors: list[models.SparseVector],
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    category: str,
    species: list[str] | None = None,
) -> None:
    payload_species = normalize_species_list(species)
    points: list[models.PointStruct] = []
    for chunk, dense, sparse in zip(chunks, dense_vectors, sparse_vectors, strict=True):
        points.append(
            models.PointStruct(
                id=str(chunk.id),
                vector={"dense": dense, "bm25": sparse},
                payload={
                    "chunk_id": str(chunk.id),
                    "document_id": str(document_id),
                    "document_version_id": str(version_id),
                    "parent_id": str(chunk.parent_id) if chunk.parent_id else None,
                    "category": category,
                    "species": payload_species,
                    "chunk_role": chunk.role,
                    "page_from": chunk.page_from,
                    "page_to": chunk.page_to,
                    "heading_path": chunk.heading_path,
                    "block_type": chunk.block_type,
                    "token_count": chunk.token_count,
                    "content_hash": _content_hash(chunk.content),
                },
            )
        )
    for start in range(0, len(points), 64):
        client.upsert(
            collection_name=settings.qdrant_collection,
            points=points[start : start + 64],
            wait=True,
        )


def _content_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def delete_version_points(client: QdrantClient, version_id: uuid.UUID) -> None:
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_version_id",
                        match=models.MatchValue(value=str(version_id)),
                    )
                ]
            )
        ),
        wait=True,
    )


def count_version_points(client: QdrantClient, version_id: uuid.UUID) -> int:
    result = client.count(
        collection_name=settings.qdrant_collection,
        count_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_version_id",
                    match=models.MatchValue(value=str(version_id)),
                )
            ]
        ),
        exact=True,
    )
    return int(result.count)


def search_dense(
    client: QdrantClient,
    query_vector: list[float],
    version_ids: list[uuid.UUID | str],
    limit: int,
    category: str | None = None,
    species: str | None = None,
) -> list[SearchHit]:
    result = client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        using="dense",
        query_filter=version_filter(version_ids, category, species=species),
        limit=limit,
        with_payload=True,
    )
    return [
        SearchHit(chunk_id=str(p.id), score=float(p.score), payload=p.payload or {})
        for p in result.points
    ]


def search_sparse(
    client: QdrantClient,
    query_vector: models.SparseVector,
    version_ids: list[uuid.UUID | str],
    limit: int,
    category: str | None = None,
    species: str | None = None,
) -> list[SearchHit]:
    if not query_vector.indices:
        return []
    result = client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        using="bm25",
        query_filter=version_filter(version_ids, category, species=species),
        limit=limit,
        with_payload=True,
    )
    return [
        SearchHit(chunk_id=str(p.id), score=float(p.score), payload=p.payload or {})
        for p in result.points
    ]
