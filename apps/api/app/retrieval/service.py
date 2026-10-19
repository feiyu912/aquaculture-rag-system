from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ingestion.embedder import Embedder
from app.models import KbChunk, KbDocument, KbDocumentVersion
from app.query.ir import QueryIR, build_query_ir
from app.retrieval.bm25 import CUSTOM_TERMS, BM25SparseEncoder, tokenize
from app.retrieval.rerank import NoopReranker, Reranker
from app.retrieval.rrf import rrf_fuse
from app.retrieval.sufficiency import Sufficiency, assess_evidence
from app.retrieval.vector_store import SearchHit, get_client, search_dense, search_sparse
from app.species import detect_species, normalize_species_list, parse_species

SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])")
VALID_MODES = ("dense", "bm25", "hybrid", "hybrid_rerank")


@dataclass(slots=True)
class Evidence:
    source_index: int
    document_id: uuid.UUID
    version_id: uuid.UUID
    parent_chunk_id: uuid.UUID
    child_chunk_id: uuid.UUID
    title: str
    version_no: int
    page: int
    quote: str
    content: str
    location: dict | None
    score: float
    species: list[str] = field(default_factory=list)
    heading_path: list[str] = field(default_factory=list)

    def as_source(self) -> dict:
        return {
            "source_id": f"S{self.source_index}",
            "index": self.source_index,
            "document_id": str(self.document_id),
            "version_id": str(self.version_id),
            "version_no": self.version_no,
            "title": self.title,
            "species": self.species,
            "page": self.page,
            "quote": self.quote,
            "heading_path": self.heading_path,
            "location": self.location,
        }


@dataclass(slots=True)
class RetrievalResult:
    evidence: list[Evidence]
    active_versions: list[uuid.UUID]
    timings: dict
    rankings: dict
    config: dict
    sufficient: bool = True
    gate: dict = field(default_factory=dict)


def normalize_mode(mode: str | None) -> str:
    value = (mode or settings.default_retrieval_mode).strip().lower()
    if value not in VALID_MODES:
        raise ValueError(f"unsupported retrieval mode: {mode}")
    return value


def _excerpt(text: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def best_sentence(text: str, query: str, limit: int = 220, max_sentences: int = 2) -> str:
    """Pick the sentences with the strongest query overlap, preserving order."""
    if not text:
        return ""
    if text.lstrip().startswith("|"):
        return _excerpt(text, limit)
    sentences = [s.strip() for s in SENTENCE_RE.split(text) if s.strip()]
    if not sentences:
        return _excerpt(text, limit)
    query_tokens = set(tokenize(query))
    domain_terms = set(CUSTOM_TERMS)
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        sentence_tokens = set(tokenize(sentence))
        shared = query_tokens & sentence_tokens
        weighted = sum(3.0 if token in domain_terms else 1.0 for token in shared)
        density = weighted / (len(sentence_tokens) + 1)
        scored.append((weighted * 2.0 + density, index, sentence))
    chosen = sorted(scored, key=lambda item: (-item[0], item[1]))[:max_sentences]
    ordered = [sentence for _, _, sentence in sorted(chosen, key=lambda item: item[1])]
    return _excerpt(" ".join(ordered), limit)


async def get_active_versions(db: AsyncSession) -> list[uuid.UUID]:
    result = await db.execute(
        select(KbDocument.current_version_id).where(
            KbDocument.status == "active",
            KbDocument.current_version_id.is_not(None),
        )
    )
    return [row[0] for row in result.all() if row[0] is not None]


async def _active_version_rows(
    db: AsyncSession,
) -> tuple[list[uuid.UUID], list[str]]:
    rows = (
        await db.execute(
            select(KbDocument.current_version_id, KbDocument.species).where(
                KbDocument.status == "active",
                KbDocument.current_version_id.is_not(None),
            )
        )
    ).all()
    versions: list[uuid.UUID] = []
    options: set[str] = set()
    for version_id, species in rows:
        if version_id is None:
            continue
        versions.append(version_id)
        options.update(normalize_species_list(species))
    return versions, sorted(options)


async def retrieve(
    db: AsyncSession,
    question: str,
    embedder: Embedder,
    bm25: BM25SparseEncoder,
    reranker: Reranker | None = None,
    top_k: int | None = None,
    category: str | None = None,
    species: str | None = None,
    mode: str = "hybrid",
) -> RetrievalResult:
    started = time.perf_counter()
    mode = normalize_mode(mode)
    active_versions, species_options = await _active_version_rows(db)
    query_ir: QueryIR | None = None
    if settings.enable_query_ir:
        query_ir = build_query_ir(
            question,
            species_options,
            explicit_species=species,
            explicit_category=category,
        )
    if not active_versions:
        gate = Sufficiency(False, "no_active_versions", [], [], 0.0, 0.0, 0.0, None)
        return RetrievalResult(
            evidence=[],
            active_versions=[],
            timings={"retrieval_ms": 0},
            rankings={},
            config=_config(mode, None, None, "none", gate, query_ir),
            sufficient=False,
            gate=gate.as_dict(),
        )

    if query_ir is not None:
        species_filter = query_ir.species_filter
        category_filter = query_ir.category_filter
    else:
        species_filter = parse_species(species)[0] if species and species.strip() else None
        if species_filter is None:
            species_filter = detect_species(question, species_options)
        category_filter = category

    client = get_client()
    query_dense = embedder.embed_query(question)
    query_sparse = bm25.query_vector(question)
    dense_hits: list[SearchHit] = []
    sparse_hits: list[SearchHit] = []
    dense_ms = 0.0
    sparse_ms = 0.0
    try:
        if mode in {"dense", "hybrid", "hybrid_rerank"}:
            dense_started = time.perf_counter()
            dense_hits = await asyncio.to_thread(
                search_dense,
                client,
                query_dense,
                active_versions,
                settings.dense_top_k,
                category_filter,
                species_filter,
            )
            dense_ms = (time.perf_counter() - dense_started) * 1000
        if mode in {"bm25", "hybrid", "hybrid_rerank"}:
            sparse_started = time.perf_counter()
            sparse_hits = await asyncio.to_thread(
                search_sparse,
                client,
                query_sparse,
                active_versions,
                settings.bm25_top_k,
                category_filter,
                species_filter,
            )
            sparse_ms = (time.perf_counter() - sparse_started) * 1000
    finally:
        client.close()

    rank_lists: list[list[str]] = []
    if dense_hits:
        rank_lists.append([hit.chunk_id for hit in dense_hits])
    if sparse_hits:
        rank_lists.append([hit.chunk_id for hit in sparse_hits])

    fused = (
        rrf_fuse(
            rank_lists,
            k=settings.rrf_k,
            limit=max((top_k or settings.rerank_top_k) * 4, 24),
        )
        if rank_lists
        else []
    )
    rankings = {
        "dense": [hit.chunk_id for hit in dense_hits],
        "sparse": [hit.chunk_id for hit in sparse_hits],
        "fused": [chunk_id for chunk_id, _ in fused],
    }
    timings = {
        "dense_ms": round(dense_ms, 1),
        "sparse_ms": round(sparse_ms, 1),
        "retrieval_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if not fused:
        gate = Sufficiency(False, "no_hits", [], [], 0.0, 0.0, 0.0, None)
        return RetrievalResult(
            evidence=[],
            active_versions=active_versions,
            timings=timings,
            rankings=rankings,
            config=_config(mode, species_filter, category_filter, "none", gate, query_ir),
            sufficient=False,
            gate=gate.as_dict(),
        )

    fused_ids = [uuid.UUID(chunk_id) for chunk_id, _ in fused]
    rows = (await db.execute(select(KbChunk).where(KbChunk.id.in_(fused_ids)))).scalars().all()
    child_by_id = {row.id: row for row in rows}

    parent_ids = {row.parent_id for row in rows if row.parent_id}
    parents = (
        (await db.execute(select(KbChunk).where(KbChunk.id.in_(parent_ids)))).scalars().all()
        if parent_ids
        else []
    )
    parent_by_id = {row.id: row for row in parents}

    version_ids = {row.document_version_id for row in rows}
    versions = (
        (await db.execute(select(KbDocumentVersion).where(KbDocumentVersion.id.in_(version_ids))))
        .scalars()
        .all()
    )
    version_by_id = {row.id: row for row in versions}

    doc_ids = {row.document_id for row in versions}
    docs = (
        (await db.execute(select(KbDocument).where(KbDocument.id.in_(doc_ids)))).scalars().all()
        if doc_ids
        else []
    )
    doc_by_id = {row.id: row for row in docs}

    grouped: dict[uuid.UUID, dict] = {}
    for chunk_id, score in fused:
        child = child_by_id.get(uuid.UUID(chunk_id))
        if child is None:
            continue
        parent = parent_by_id.get(child.parent_id) if child.parent_id else None
        parent = parent or child
        current = grouped.get(parent.id)
        if current is None:
            grouped[parent.id] = {"parent": parent, "child": child, "score": score}
        elif score > current["score"]:
            current["child"] = child
            current["score"] = score

    candidates = sorted(grouped.values(), key=lambda item: -item["score"])
    if top_k:
        candidates = candidates[: max(top_k * 2, top_k)]

    reranker_name = "none"
    if mode == "hybrid_rerank":
        active_reranker: Reranker = reranker or NoopReranker()
        reranker_name = active_reranker.name
        candidates_for_rerank = [
            (str(item["parent"].id), item["parent"].content) for item in candidates
        ]
        reranked = active_reranker.rerank(
            question, candidates_for_rerank, top_k or settings.rerank_top_k
        )
        by_parent_id = {uuid.UUID(chunk_id): score for chunk_id, score in reranked}
        ordered_ids = [uuid.UUID(chunk_id) for chunk_id, _ in reranked]
        candidate_by_id = {item["parent"].id: item for item in candidates}
        candidate_iter = [
            candidate_by_id[parent_id] for parent_id in ordered_ids if parent_id in candidate_by_id
        ]
    else:
        by_parent_id = {item["parent"].id: item["score"] for item in candidates}
        candidate_iter = candidates

    evidence: list[Evidence] = []
    for item in candidate_iter:
        if item["parent"].id not in by_parent_id:
            continue
        parent: KbChunk = item["parent"]
        child: KbChunk = item["child"]
        if len(parent.content.strip()) < 40:
            continue
        version = version_by_id.get(parent.document_version_id)
        doc = doc_by_id.get(version.document_id) if version else None
        if version is None or doc is None:
            continue
        location = parent.locations[0] if parent.locations else None
        evidence.append(
            Evidence(
                source_index=len(evidence) + 1,
                document_id=doc.id,
                version_id=version.id,
                parent_chunk_id=parent.id,
                child_chunk_id=child.id,
                title=doc.title,
                version_no=version.version_no,
                page=parent.page_from,
                quote=best_sentence(parent.content, question, 260),
                content=_excerpt(parent.content, 1800),
                location=location,
                score=by_parent_id[parent.id],
                species=normalize_species_list(doc.species),
                heading_path=list(parent.heading_path or []),
            )
        )
        if len(evidence) >= (top_k or settings.max_sources):
            break

    gate = assess_evidence(
        question,
        [item.content for item in evidence],
        min_terms=settings.evidence_min_terms,
        min_weight=settings.evidence_min_weight,
        min_coverage=settings.evidence_min_coverage,
        domain_terms=set(species_options),
    )
    if not gate.sufficient:
        evidence = []

    timings["retrieval_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return RetrievalResult(
        evidence=evidence,
        active_versions=active_versions,
        timings=timings,
        rankings=rankings,
        config=_config(mode, species_filter, category_filter, reranker_name, gate, query_ir),
        sufficient=gate.sufficient,
        gate=gate.as_dict(),
    )


def _config(
    mode: str,
    species_filter: str | None,
    category_filter: str | None,
    reranker: str,
    gate: Sufficiency,
    query_ir: QueryIR | None = None,
) -> dict:
    return {
        "dense_top_k": settings.dense_top_k,
        "bm25_top_k": settings.bm25_top_k,
        "rrf_k": settings.rrf_k,
        "rerank_top_k": settings.rerank_top_k,
        "embedding": settings.embedding_model,
        "collection": settings.qdrant_collection,
        "retrieval_mode": mode,
        "species_filter": species_filter,
        "category_filter": category_filter,
        "reranker": reranker,
        "query_ir": query_ir.model_dump() if query_ir else None,
        "evidence_min_terms": settings.evidence_min_terms,
        "evidence_min_weight": settings.evidence_min_weight,
        "evidence_min_coverage": settings.evidence_min_coverage,
        "evidence_gate": gate.as_dict(),
    }
