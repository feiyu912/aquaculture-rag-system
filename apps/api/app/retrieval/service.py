from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.graph.service import expand_entities, graph_chunk_ids, load_graph
from app.ingestion.embedder import Embedder
from app.ingestion.pipeline import chunk_config_hash
from app.models import KbChunk, KbDocument, KbDocumentVersion
from app.query.decompose import decompose_question
from app.query.expand import alias_variants
from app.query.ir import QueryIR, build_query_ir
from app.query.planner import LLMQueryPlanner, should_use_llm_planner
from app.query.router import select_modules
from app.retrieval.bm25 import CUSTOM_TERMS, BM25SparseEncoder, tokenize
from app.retrieval.index_manifest import check_manifest
from app.retrieval.requirements import (
    Requirement,
    assess_requirements,
    build_requirements,
    build_supplemental_query,
)
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
        location = self.location or {}
        return {
            "source_id": f"S{self.source_index}",
            "index": self.source_index,
            "document_id": str(self.document_id),
            "version_id": str(self.version_id),
            "version_no": self.version_no,
            "chunk_id": str(self.parent_chunk_id),
            "child_chunk_id": str(self.child_chunk_id),
            "title": self.title,
            "species": self.species,
            "page": self.page,
            "quote": self.quote,
            "heading_path": self.heading_path,
            "location": self.location,
            # Convenience fields for PDF.js; ``location`` remains the canonical
            # full record for backward compatibility.
            "bbox": location.get("bbox"),
            "coordinate_system": location.get("coordinate_system"),
            "origin": location.get("origin"),
            "rotation": location.get("rotation"),
            "page_width": location.get("page_width"),
            "page_height": location.get("page_height"),
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


EVIDENCE_ALIASES = {
    "溶氧": "溶解氧",
    "溶氧量": "溶解氧",
    "do": "溶解氧",
    "ph": "酸碱度",
    "ph值": "酸碱度",
}


def _canonical_term(token: str) -> str:
    return EVIDENCE_ALIASES.get(token.lower(), token.lower())


def best_sentence(text: str, query: str, limit: int = 220, max_sentences: int = 2) -> str:
    """Pick the sentences with the strongest query overlap, preserving order."""
    if not text:
        return ""
    if text.lstrip().startswith("|"):
        return _excerpt(text, limit)
    sentences = [s.strip() for s in SENTENCE_RE.split(text) if s.strip()]
    if not sentences:
        return _excerpt(text, limit)
    query_tokens = {_canonical_term(token) for token in tokenize(query)}
    domain_terms = set(CUSTOM_TERMS)
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        sentence_tokens = {_canonical_term(token) for token in tokenize(sentence)}
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


async def _embedding_mismatches(
    db: AsyncSession, version_ids: list[uuid.UUID]
) -> list[dict[str, str]]:
    """Detect active versions indexed with a different embedding model.

    Reusing a Qdrant collection after switching from the development hashing
    embedder to BGE-M3 would mix incompatible vectors.  Refuse retrieval until
    the caller rebuilds the index instead of returning silently meaningless
    neighbours.
    """
    if not version_ids:
        return []
    rows = (
        await db.execute(
            select(KbDocumentVersion.id, KbDocumentVersion.embedding_model).where(
                KbDocumentVersion.id.in_(version_ids)
            )
        )
    ).all()
    mismatched: list[dict[str, str]] = []
    for version_id, model in rows:
        if model and model != settings.embedding_model:
            mismatched.append({"version_id": str(version_id), "embedding_model": model})
    return mismatched


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
    planner: LLMQueryPlanner | None = None,
    top_k: int | None = None,
    category: str | None = None,
    species: str | None = None,
    mode: str = "hybrid",
    search_question: str | None = None,
    _attempt: int = 0,
) -> RetrievalResult:
    started = time.perf_counter()
    mode = normalize_mode(mode)
    query_text = (search_question or question).strip()
    active_versions, species_options = await _active_version_rows(db)
    query_ir: QueryIR | None = None
    planner_trace: dict | None = None
    if settings.enable_query_ir:
        query_ir = build_query_ir(
            question,
            species_options,
            explicit_species=species,
            explicit_category=category,
        )
        if settings.enable_llm_planner and _attempt == 0:
            if not should_use_llm_planner(query_ir):
                planner_trace = {
                    "enabled": True,
                    "used_llm": False,
                    "error": None,
                    "skipped": "simple_rule_ir",
                    "duration_ms": 0.0,
                    "plan": None,
                }
            elif planner is None:
                planner_trace = {
                    "enabled": True,
                    "used_llm": False,
                    "error": "planner_unavailable",
                    "duration_ms": 0.0,
                    "plan": None,
                }
            else:
                outcome = await planner.plan(question, query_ir, species_options)
                query_ir = outcome.ir
                planner_trace = outcome.trace()
    adaptive_route = query_ir.strategy if query_ir else "simple"
    embedding_mismatches = await _embedding_mismatches(db, active_versions)
    manifest = await check_manifest(
        db,
        collection=settings.qdrant_collection,
        embedding_model=settings.embedding_model,
        vector_size=settings.qdrant_vector_size,
        chunk_config_hash=chunk_config_hash(),
    )
    base_modules = {
        "graph": settings.enable_graph_expansion,
        "decomposition": settings.enable_query_decomposition,
        "requirements": settings.enable_evidence_requirements,
        "targeted": settings.enable_targeted_retrieval,
    }
    modules = (
        select_modules(query_ir, **base_modules)
        if settings.enable_adaptive_routing
        else base_modules
    )
    manifest_ok = manifest["present"] and manifest["ok"]
    manifest_blocked = (manifest["present"] and not manifest["ok"]) or (
        settings.index_manifest_required and not manifest["present"]
    )
    # A document version can have been indexed into more than one collection
    # (e.g. legacy hash + new BGE). The collection manifest is authoritative for
    # the collection currently being queried; per-version metadata is only a
    # fallback when no manifest exists.
    version_mismatch_blocked = bool(embedding_mismatches) and not manifest_ok
    if version_mismatch_blocked or manifest_blocked:
        reason = (
            "index_embedding_mismatch" if version_mismatch_blocked else "index_manifest_mismatch"
        )
        gate = Sufficiency(False, reason, [], [], 0.0, 0.0, 0.0, None)
        return RetrievalResult(
            evidence=[],
            active_versions=active_versions,
            timings={"retrieval_ms": 0},
            rankings={},
            config=_config(
                mode,
                None,
                None,
                "none",
                gate,
                query_ir,
                route=adaptive_route,
                modules=modules,
                compatibility={
                    "configured": settings.embedding_model,
                    "mismatched": embedding_mismatches,
                    "manifest": manifest,
                },
            ),
            sufficient=False,
            gate=gate.as_dict(),
        )

    if not active_versions:
        gate = Sufficiency(False, "no_active_versions", [], [], 0.0, 0.0, 0.0, None)
        return RetrievalResult(
            evidence=[],
            active_versions=[],
            timings={"retrieval_ms": 0},
            rankings={},
            config=_config(
                mode,
                None,
                None,
                "none",
                gate,
                query_ir,
                route=adaptive_route,
                planner=planner_trace,
            ),
            sufficient=False,
            gate=gate.as_dict(),
        )

    if settings.enable_adaptive_routing and query_ir is not None:
        block_reason = route_block_reason(query_ir)
        if block_reason is not None:
            gate = Sufficiency(False, block_reason, [], [], 0.0, 0.0, 0.0, None)
            return RetrievalResult(
                evidence=[],
                active_versions=active_versions,
                timings={"retrieval_ms": 0},
                rankings={},
                config=_config(
                    mode,
                    query_ir.species_filter,
                    query_ir.category_filter,
                    "none",
                    gate,
                    query_ir,
                    route=adaptive_route,
                    modules=modules,
                    planner=planner_trace,
                ),
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

    graph_expansion = None
    graph_ids: list[str] = []
    graph_ms = 0.0
    if modules["graph"]:
        graph_started = time.perf_counter()
        graph = await load_graph(db)
        if graph.entities:
            graph_expansion = expand_entities(
                query_text,
                graph,
                max_related=settings.graph_max_related,
                max_hops=settings.graph_max_hops,
                bidirectional=settings.graph_bidirectional,
            )
            if graph_expansion.expanded_entity_ids:
                graph_ids = [
                    str(chunk_id)
                    for chunk_id in await graph_chunk_ids(
                        db,
                        graph_expansion.expanded_entity_ids,
                        active_versions,
                        category=category_filter,
                        species=species_filter,
                        limit=settings.graph_top_k,
                    )
                ]
        graph_ms = (time.perf_counter() - graph_started) * 1000

    query_variants = [query_text]
    if query_ir is not None:
        rewritten = (query_ir.rewritten_query or "").strip()
        if rewritten and rewritten not in query_variants:
            query_variants.append(rewritten)
        for task in query_ir.planner_tasks:
            inherited = str(task.get("effective_query") or "").strip()
            if inherited and inherited not in query_variants:
                query_variants.append(inherited)
        if not query_ir.planner_tasks:
            for variant in query_ir.planner_subquestions:
                inherited = _inherit_constraints(variant, query_ir)
                if inherited not in query_variants:
                    query_variants.append(inherited)
        for variant in alias_variants(question, query_ir):
            if variant not in query_variants:
                query_variants.append(variant)
    if modules["decomposition"] and query_ir is not None:
        for variant in decompose_question(question, query_ir):
            if variant not in query_variants:
                query_variants.append(variant)
    query_variants = query_variants[: max(1, settings.max_query_variants)]

    client = get_client()
    dense_rankings: list[tuple[list[SearchHit], float]] = []
    sparse_rankings: list[tuple[list[SearchHit], float]] = []
    variant_trace: list[dict] = []
    dense_ms = 0.0
    sparse_ms = 0.0

    async def _dense_search(text: str) -> tuple[list[SearchHit], float]:
        started_at = time.perf_counter()
        vector = await asyncio.to_thread(embedder.embed_query, text)
        hits = await asyncio.to_thread(
            search_dense,
            client,
            vector,
            active_versions,
            settings.dense_top_k,
            category_filter,
            species_filter,
        )
        return hits, (time.perf_counter() - started_at) * 1000

    async def _sparse_search(text: str) -> tuple[list[SearchHit], float]:
        started_at = time.perf_counter()
        vector = bm25.query_vector(text)
        hits = await asyncio.to_thread(
            search_sparse,
            client,
            vector,
            active_versions,
            settings.bm25_top_k,
            category_filter,
            species_filter,
        )
        return hits, (time.perf_counter() - started_at) * 1000

    async def _run_variant(
        index: int, variant: str
    ) -> tuple[dict, list[SearchHit], list[SearchHit], float, float]:
        weight = 1.0 if index == 0 else 0.8
        trace = {"query": variant, "weight": weight, "dense": 0, "sparse": 0}
        need_dense = mode in {"dense", "hybrid", "hybrid_rerank"}
        need_sparse = mode in {"bm25", "hybrid", "hybrid_rerank"}
        dense_task = _dense_search(variant) if need_dense else None
        sparse_task = _sparse_search(variant) if need_sparse else None
        if dense_task and sparse_task:
            (dense_hits, dense_elapsed), (sparse_hits, sparse_elapsed) = await asyncio.gather(
                dense_task, sparse_task
            )
        elif dense_task:
            dense_hits, dense_elapsed = await dense_task
            sparse_hits, sparse_elapsed = [], 0.0
        elif sparse_task:
            dense_hits, dense_elapsed = [], 0.0
            sparse_hits, sparse_elapsed = await sparse_task
        else:
            dense_hits, dense_elapsed = [], 0.0
            sparse_hits, sparse_elapsed = [], 0.0
        trace["dense"] = len(dense_hits)
        trace["sparse"] = len(sparse_hits)
        return trace, dense_hits, sparse_hits, dense_elapsed, sparse_elapsed

    try:
        variant_results = await asyncio.gather(
            *(_run_variant(index, variant) for index, variant in enumerate(query_variants))
        )
        for trace, dense_hits, sparse_hits, dense_elapsed, sparse_elapsed in variant_results:
            dense_ms += dense_elapsed
            sparse_ms += sparse_elapsed
            if dense_hits:
                dense_rankings.append((dense_hits, trace["weight"]))
            if sparse_hits:
                sparse_rankings.append((sparse_hits, trace["weight"]))
            variant_trace.append(trace)
    finally:
        client.close()

    rank_lists: list[list[str]] = []
    weights: list[float] = []
    for hits, weight in dense_rankings:
        rank_lists.append([hit.chunk_id for hit in hits])
        weights.append(weight)
    for hits, weight in sparse_rankings:
        rank_lists.append([hit.chunk_id for hit in hits])
        weights.append(weight)
    if graph_ids:
        rank_lists.append(graph_ids)
        weights.append(settings.graph_rrf_weight)

    fused = (
        rrf_fuse(
            rank_lists,
            k=settings.rrf_k,
            weights=weights,
            limit=max((top_k or settings.rerank_top_k) * 4, 24),
        )
        if rank_lists
        else []
    )
    rankings = {
        "dense": [hit.chunk_id for hit in (dense_rankings[0][0] if dense_rankings else [])],
        "sparse": [hit.chunk_id for hit in (sparse_rankings[0][0] if sparse_rankings else [])],
        "graph": graph_ids,
        "queries": variant_trace,
        "fused": [chunk_id for chunk_id, _ in fused],
    }
    timings = {
        "dense_ms": round(dense_ms, 1),
        "sparse_ms": round(sparse_ms, 1),
        "graph_ms": round(graph_ms, 1),
        "retrieval_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if not fused:
        gate = Sufficiency(False, "no_hits", [], [], 0.0, 0.0, 0.0, None)
        return RetrievalResult(
            evidence=[],
            active_versions=active_versions,
            timings=timings,
            rankings=rankings,
            config=_config(
                mode,
                species_filter,
                category_filter,
                "none",
                gate,
                query_ir,
                graph_expansion.as_dict() if graph_expansion else None,
                route=adaptive_route,
                modules=modules,
            ),
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

    requirements: list[Requirement] = []
    if modules["requirements"]:
        requirements = assess_requirements(
            build_requirements(query_ir), [item.content for item in evidence]
        )
    gate = _assess_with_requirements(
        question,
        evidence,
        requirements,
        species_options,
        fallback_reason=None,
    )

    targeted_trace: dict | None = None
    if not gate.sufficient and modules["targeted"] and _attempt < settings.max_targeted_retrieval:
        supplement = build_supplemental_query(
            question,
            requirements,
            gate.missing_terms,
        )
        if supplement:
            second = await retrieve(
                db,
                question,
                embedder,
                bm25,
                reranker=reranker,
                planner=planner,
                top_k=top_k,
                category=category,
                species=species,
                mode=mode,
                search_question=supplement,
                _attempt=_attempt + 1,
            )
            targeted_trace = {
                "attempt": _attempt + 1,
                "supplement": supplement,
                "insufficient_reason": gate.reason,
                "second_sufficient": second.sufficient,
            }
            if second.sufficient:
                merged = _merge_evidence(evidence, second.evidence)
                if merged:
                    evidence = merged[: settings.max_sources]
                    for index, item in enumerate(evidence, start=1):
                        item.source_index = index
                    gate = _assess_with_requirements(
                        question,
                        evidence,
                        requirements,
                        species_options,
                        fallback_reason=None,
                    )
                rankings = _merge_rankings(rankings, second.rankings)
                timings["targeted_ms"] = second.timings.get("retrieval_ms", 0)

    if not gate.sufficient:
        evidence = []

    config = _config(
        mode,
        species_filter,
        category_filter,
        reranker_name,
        gate,
        query_ir,
        graph_expansion.as_dict() if graph_expansion else None,
        route=adaptive_route,
        modules=modules,
        planner=planner_trace,
        compatibility={
            "configured": settings.embedding_model,
            "mismatched": embedding_mismatches,
            "manifest": manifest,
        },
    )
    if requirements:
        config["evidence_requirements"] = [item.as_dict() for item in requirements]
    if targeted_trace:
        config["targeted_retrieval"] = targeted_trace
    timings["retrieval_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return RetrievalResult(
        evidence=evidence,
        active_versions=active_versions,
        timings=timings,
        rankings=rankings,
        config=config,
        sufficient=gate.sufficient,
        gate=gate.as_dict(),
    )


def _inherit_constraints(subquestion: str, ir: QueryIR) -> str:
    """Prefix a planner sub-question with the original hard/soft facets."""
    parts = [subquestion]
    for value in [*ir.species[:1], *ir.growth_stage[:1]]:
        if value and value not in subquestion:
            parts.insert(0, value)
    return " ".join(parts)


def _assess_with_requirements(
    question: str,
    evidence: list[Evidence],
    requirements: list[Requirement],
    species_options: list[str],
    *,
    fallback_reason: str | None,
) -> Sufficiency:
    gate = assess_evidence(
        question,
        [item.content for item in evidence],
        min_terms=settings.evidence_min_terms,
        min_weight=settings.evidence_min_weight,
        min_coverage=settings.evidence_min_coverage,
        domain_terms=set(species_options),
    )
    if fallback_reason and not gate.sufficient:
        return Sufficiency(
            False,
            fallback_reason,
            gate.query_terms,
            gate.matched_terms,
            gate.matched_weight,
            gate.total_weight,
            gate.coverage,
            None,
            gate.missing_terms,
        )
    if requirements and not all(item.covered for item in requirements):
        missing = [item for item in requirements if not item.covered]
        missing_terms = [
            term for item in missing for term in item.terms if term not in item.matched_terms
        ]
        return Sufficiency(
            False,
            "missing_requirements",
            gate.query_terms,
            gate.matched_terms,
            gate.matched_weight,
            gate.total_weight,
            gate.coverage,
            gate.best_index,
            list(dict.fromkeys(missing_terms)),
        )
    return gate


def _merge_evidence(first: list[Evidence], second: list[Evidence]) -> list[Evidence]:
    by_parent: dict[uuid.UUID, Evidence] = {}
    for item in [*first, *second]:
        current = by_parent.get(item.parent_chunk_id)
        if current is None or item.score > current.score:
            by_parent[item.parent_chunk_id] = item
    return sorted(by_parent.values(), key=lambda item: -item.score)


def _merge_rankings(first: dict, second: dict) -> dict:
    merged = dict(first)
    for key in ("dense", "sparse", "graph"):
        merged[key] = list(dict.fromkeys([*(first.get(key) or []), *(second.get(key) or [])]))
    merged["targeted_fused"] = second.get("fused") or []
    merged["fused"] = list(
        dict.fromkeys([*(first.get("fused") or []), *(second.get("fused") or [])])
    )
    return merged


def route_block_reason(query_ir: QueryIR) -> str | None:
    """Conservative deterministic guards for routes that need absent tools/metadata."""
    if query_ir.strategy == "calculation":
        return "calculation_tool_unavailable"
    if query_ir.strategy == "regulation" and query_ir.requires_current_regulation:
        return "regulation_metadata_unavailable"
    return None


def _config(
    mode: str,
    species_filter: str | None,
    category_filter: str | None,
    reranker: str,
    gate: Sufficiency,
    query_ir: QueryIR | None = None,
    graph_expansion: dict | None = None,
    route: str | None = None,
    modules: dict | None = None,
    compatibility: dict | None = None,
    planner: dict | None = None,
) -> dict:
    return {
        "dense_top_k": settings.dense_top_k,
        "bm25_top_k": settings.bm25_top_k,
        "rrf_k": settings.rrf_k,
        "rerank_top_k": settings.rerank_top_k,
        "embedding": settings.embedding_model,
        "embedding_dimension": settings.qdrant_vector_size,
        "bm25": {
            "k1": settings.bm25_k1,
            "b": settings.bm25_b,
            "avg_len": settings.bm25_avg_len,
            "tokenizer": "jieba+custom_terms",
        },
        "reranker_model": settings.reranker_model,
        "collection": settings.qdrant_collection,
        "retrieval_mode": mode,
        "species_filter": species_filter,
        "category_filter": category_filter,
        "reranker": reranker,
        "query_ir": query_ir.model_dump() if query_ir else None,
        "graph_expansion": graph_expansion,
        "graph_top_k": settings.graph_top_k,
        "graph_rrf_weight": settings.graph_rrf_weight,
        "graph_max_hops": settings.graph_max_hops,
        "graph_max_related": settings.graph_max_related,
        "graph_bidirectional": settings.graph_bidirectional,
        "query_decomposition": settings.enable_query_decomposition,
        "contextual_retrieval": settings.enable_contextual_retrieval,
        "max_query_variants": settings.max_query_variants,
        "adaptive_route": route,
        "adaptive_routing_enabled": settings.enable_adaptive_routing,
        "adaptive_modules": modules or {},
        "llm_planner": planner,
        "index_compatibility": compatibility
        or {
            "configured": settings.embedding_model,
            "mismatched": [],
        },
        "evidence_min_terms": settings.evidence_min_terms,
        "evidence_min_weight": settings.evidence_min_weight,
        "evidence_min_coverage": settings.evidence_min_coverage,
        "evidence_gate": gate.as_dict(),
    }
