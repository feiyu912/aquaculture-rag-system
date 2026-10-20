from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.graph.service import expand_entities, graph_chunk_matches, load_graph
from app.ingestion.embedder import Embedder
from app.ingestion.pipeline import chunk_config_hash
from app.models import KbChunk, KbDocument, KbDocumentVersion
from app.query.decompose import decompose_question
from app.query.expand import alias_variants
from app.query.ir import QueryIR, build_query_ir
from app.query.planner import LLMQueryPlanner, should_use_llm_planner
from app.query.router import select_modules
from app.query.sources import (
    SourceAnchor,
    extract_source_anchors,
    facet_covered,
    facet_terms,
    has_threshold_cue,
    matches_title,
    order_round_robin,
)
from app.retrieval.bm25 import CUSTOM_TERMS, BM25SparseEncoder, bm25_config_hash, tokenize
from app.retrieval.index_manifest import check_manifest
from app.retrieval.requirements import (
    Requirement,
    assess_requirements,
    build_requirements,
    build_targeted_queries,
    term_present,
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
    # Populated only for chunks reached through a verified graph edge: which
    # entity matched, the relation path that reached it, and the edge
    # provenance.  None keeps ordinary vector hits distinguishable.
    graph_provenance: dict | None = None

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
            "graph_provenance": self.graph_provenance,
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


# Retrying these cannot add evidence: the question itself has no domain terms,
# the first pass had no hits at all, or the gate already rejected the answer as
# a time-sensitive regulation with no verified current version.
TARGETED_SKIP_REASONS = {
    "no_query_terms",
    "no_evidence",
    "current_regulation_unverified",
}


EVIDENCE_ALIASES = {
    "溶氧": "溶解氧",
    "溶氧量": "溶解氧",
    "do": "溶解氧",
    "ph": "酸碱度",
    "ph值": "酸碱度",
}


def _covering_first(items: list[Evidence], terms: list[str]) -> list[Evidence]:
    """Move evidence that states a missing facet into the visible slots.

    The retry pool is larger than ``max_sources``; a chunk that covers the
    missing facet can rank below the cut after merging.  Keeping it in the
    visible window is what makes ``sufficient_after=true`` honest: the gate
    judged evidence the answer can actually cite.
    """
    covering = [
        item
        for item in items
        if any(
            term_present(term, f"{item.content}\n{' '.join(item.heading_path)}")
            for term in terms
        )
    ]
    if not covering:
        return items
    seen = {id(item) for item in covering}
    return covering + [item for item in items if id(item) not in seen]


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


async def _resolve_source_versions(
    db: AsyncSession, anchors: list[SourceAnchor], active_versions: list[uuid.UUID]
) -> dict[str, list[uuid.UUID]]:
    """Map a cited standard code to active versions whose *title* carries it.

    Resolution uses document titles only.  It never consults the evaluation gold
    set, so a wrong code simply resolves to nothing and is reported as such.
    """
    if not anchors:
        return {}
    rows = (
        await db.execute(
            select(KbDocument.title, KbDocument.current_version_id).where(
                KbDocument.status == "active",
                KbDocument.current_version_id.is_not(None),
            )
        )
    ).all()
    active = set(active_versions)
    resolved: dict[str, list[uuid.UUID]] = {}
    for anchor in anchors:
        resolved[anchor.code] = [
            version_id
            for title, version_id in rows
            if version_id in active and matches_title(title, anchor)
        ]
    return resolved


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
    keep_insufficient_evidence: bool = False,
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
        bm25_config_hash=bm25_config_hash(),
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

    # Source anchors: only when the user explicitly cites at least two standards
    # does per-source evidence reservation make sense.  A single citation keeps
    # the ordinary global ranking (and its trace records why it was skipped).
    source_anchors: list[SourceAnchor] = []
    source_versions: dict[str, list[uuid.UUID]] = {}
    source_trace: dict | None = None
    if settings.enable_source_aware_retrieval:
        cited = extract_source_anchors(question, limit=settings.source_anchor_max)
        resolved = await _resolve_source_versions(db, cited, active_versions) if cited else {}
        usable = [anchor for anchor in cited if resolved.get(anchor.code)]
        if len(usable) >= 2:
            source_anchors = usable
            source_versions = {anchor.code: resolved[anchor.code] for anchor in usable}
        source_trace = {
            "enabled": True,
            "cited": [anchor.as_dict() for anchor in cited],
            "resolved": {code: [str(v) for v in versions] for code, versions in resolved.items()},
            "active": len(usable) >= 2,
            "reason": None if len(usable) >= 2 else (
                "fewer_than_two_resolved_sources" if cited else "no_cited_source"
            ),
        }

    graph_expansion = None
    graph_ids: list[str] = []
    graph_provenance_by_child: dict[str, dict] = {}
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
                matches = await graph_chunk_matches(
                    db,
                    graph_expansion.expanded_entity_ids,
                    active_versions,
                    category=category_filter,
                    species=species_filter,
                    limit=settings.graph_top_k,
                )
                graph_ids = [str(item["chunk_id"]) for item in matches]
                entity_names = {entity.id: entity.name for entity in graph.entities.values()}
                paths_by_entity: dict[str, list[str]] = {
                    str(entity_id): [entity_names[entity_id]]
                    for entity_id in graph_expansion.seed_entity_ids
                    if entity_id in entity_names
                }
                for edge in graph_expansion.relation_trace:
                    path_ids = edge.get("path_entity_ids") or []
                    if path_ids:
                        paths_by_entity[path_ids[-1]] = list(edge.get("path") or [])
                for match in matches:
                    matched = [str(item) for item in match["entity_ids"]]
                    graph_provenance_by_child[str(match["chunk_id"])] = {
                        "matched_entities": [
                            entity_names.get(item, item) for item in match["entity_ids"]
                        ],
                        "paths": [paths_by_entity.get(item, [entity_names.get(item, item)]) for item in matched],
                        "mention_count": match["mention_count"],
                        "seed_terms": graph_expansion.seed_terms,
                    }
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
            # Each task also needs the document-side alias (e.g. 溶解氧→溶氧量);
            # otherwise a correct task can miss the exact source wording.
            for task_variant in alias_variants(inherited, query_ir, limit=1):
                if task_variant not in query_variants:
                    query_variants.append(task_variant)
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

    async def _dense_search(
        text: str,
        versions: list[uuid.UUID] | None = None,
        limit: int | None = None,
    ) -> tuple[list[SearchHit], float]:
        started_at = time.perf_counter()
        vector = await asyncio.to_thread(embedder.embed_query, text)
        hits = await asyncio.to_thread(
            search_dense,
            client,
            vector,
            versions or active_versions,
            limit or settings.dense_top_k,
            category_filter,
            species_filter,
        )
        return hits, (time.perf_counter() - started_at) * 1000

    async def _sparse_search(
        text: str,
        versions: list[uuid.UUID] | None = None,
        limit: int | None = None,
    ) -> tuple[list[SearchHit], float]:
        started_at = time.perf_counter()
        vector = bm25.query_vector(text)
        hits = await asyncio.to_thread(
            search_sparse,
            client,
            vector,
            versions or active_versions,
            limit or settings.bm25_top_k,
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

    async def _run_anchor_search(anchor: SourceAnchor) -> dict:
        """Facet queries restricted to the versions of one cited standard."""
        versions = source_versions[anchor.code]
        texts = [question]
        facet_query = " ".join(facet_terms(query_ir))
        if facet_query and facet_query not in question:
            texts.append(facet_query)
        need_dense = mode in {"dense", "hybrid", "hybrid_rerank"}
        need_sparse = mode in {"bm25", "hybrid", "hybrid_rerank"}
        lists: list[list[str]] = []
        weights: list[float] = []
        for index, text in enumerate(texts[:2]):
            tasks = []
            if need_dense:
                tasks.append(_dense_search(text, versions, settings.source_anchor_top_k))
            if need_sparse:
                tasks.append(_sparse_search(text, versions, settings.source_anchor_top_k))
            results = await asyncio.gather(*tasks) if tasks else []
            for hits, _elapsed in results:
                if hits:
                    lists.append([hit.chunk_id for hit in hits])
                    weights.append(1.0 if index == 0 else 0.8)
        fused_anchor = (
            rrf_fuse(lists, k=settings.rrf_k, weights=weights, limit=settings.source_anchor_top_k)
            if lists
            else []
        )
        return {
            "anchor": anchor,
            "queries": texts[:2],
            "fused": fused_anchor,
            "candidates": len(fused_anchor),
        }

    try:
        variant_task = asyncio.gather(
            *(_run_variant(index, variant) for index, variant in enumerate(query_variants))
        )
        anchor_task = asyncio.gather(*(_run_anchor_search(anchor) for anchor in source_anchors))
        variant_results, anchor_results = await asyncio.gather(variant_task, anchor_task)
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
    anchor_child_ids = [
        uuid.UUID(chunk_id) for result in anchor_results for chunk_id, _score in result["fused"]
    ]
    if not fused and not anchor_child_ids:
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
                source_aware=source_trace,
            ),
            sufficient=False,
            gate=gate.as_dict(),
        )

    all_child_ids = list(
        dict.fromkeys([*(uuid.UUID(chunk_id) for chunk_id, _score in fused), *anchor_child_ids])
    )
    rows = (await db.execute(select(KbChunk).where(KbChunk.id.in_(all_child_ids)))).scalars().all()
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

    # Per-task rerank: a planner task is a focused sub-question.  Scoring each
    # parent with ``max(question, task)`` keeps a task-specific passage from
    # being buried by the comparison framing of the original question.
    rerank_queries = [question]
    if query_ir is not None:
        for task in query_ir.planner_tasks[:3]:
            value = str(task.get("effective_query") or "").strip()
            if value and value not in rerank_queries:
                rerank_queries.append(value)
    rerank_queries = rerank_queries[:4]

    active_reranker: Reranker | None = None
    reranker_name = "none"
    if mode == "hybrid_rerank":
        active_reranker = reranker or NoopReranker()
        reranker_name = active_reranker.name

    by_parent_id: dict[uuid.UUID, float] = {}
    ordered_parent_ids: list[uuid.UUID] = []
    if active_reranker is not None:
        candidates_for_rerank = [
            (str(item["parent"].id), item["parent"].content) for item in candidates
        ]
        scores: dict[str, float] = {}
        for text in rerank_queries:
            for chunk_id, score in active_reranker.rerank(
                text, candidates_for_rerank, len(candidates_for_rerank)
            ):
                if chunk_id not in scores or score > scores[chunk_id]:
                    scores[chunk_id] = score
        by_parent_id = {uuid.UUID(chunk_id): score for chunk_id, score in scores.items()}
        ordered_parent_ids = [
            uuid.UUID(chunk_id) for chunk_id, _score in sorted(scores.items(), key=lambda kv: -kv[1])
        ]
    else:
        by_parent_id = {item["parent"].id: item["score"] for item in candidates}
        ordered_parent_ids = [item["parent"].id for item in candidates]

    item_by_parent: dict[uuid.UUID, dict] = {item["parent"].id: item for item in candidates}
    facets = facet_terms(query_ir)
    anchor_groups: list[list[uuid.UUID]] = []
    anchor_trace: list[dict] = []
    for result in anchor_results:
        per_parent: dict[uuid.UUID, dict] = {}
        for chunk_id, score in result["fused"]:
            child = child_by_id.get(uuid.UUID(chunk_id))
            if child is None:
                continue
            parent = parent_by_id.get(child.parent_id) if child.parent_id else None
            parent = parent or child
            current = per_parent.get(parent.id)
            if current is None or score > current["score"]:
                per_parent[parent.id] = {"parent": parent, "child": child, "score": score}
        pool = sorted(per_parent.values(), key=lambda item: -item["score"])
        # Facet coverage is an evidence requirement: a DB46 chunk about 尾水
        # treatment is not evidence for a 溶解氧 question even if it is in the
        # same standard.  If no candidate mentions the facet we fall back to the
        # full pool and record it, instead of fabricating coverage.
        covered = [item for item in pool if facet_covered(item["parent"].content, facets)]
        facet_filter = "applied" if covered else "fallback_no_facet_match"
        pool = (covered or pool)[: settings.source_anchor_rerank_limit]
        anchor_scores: dict[uuid.UUID, float] = {}
        ordered_anchor: list[uuid.UUID] = []
        if active_reranker is not None and pool:
            # Rerank the evidence window (the sentence that answers the
            # question), not the full parent: parent chunks can contain
            # unrelated glossary text that dominates/masks the answer.
            window_texts = [
                (str(item["parent"].id), best_sentence(item["parent"].content, question, 300))
                for item in pool
            ]
            ranked = active_reranker.rerank(question, window_texts, len(window_texts))
            anchor_scores = {uuid.UUID(chunk_id): score for chunk_id, score in ranked}
            window_by_parent = {uuid.UUID(chunk_id): text for chunk_id, text in window_texts}
            # Within one source, a passage that states the numeric limit is
            # better evidence for a "最低要求" question than one that merely
            # mentions the facet.  Rerank order breaks ties.
            rerank_rank = {
                uuid.UUID(chunk_id): index for index, (chunk_id, _score) in enumerate(ranked)
            }
            ordered_anchor = sorted(
                rerank_rank,
                key=lambda parent_id: (
                    not has_threshold_cue(window_by_parent.get(parent_id, "")),
                    rerank_rank[parent_id],
                ),
            )
        else:
            ordered_anchor = [item["parent"].id for item in pool]
            anchor_scores = {item["parent"].id: item["score"] for item in pool}
        for parent_id in ordered_anchor:
            item_by_parent.setdefault(parent_id, per_parent[parent_id])
            by_parent_id.setdefault(parent_id, anchor_scores.get(parent_id, 0.0))
        anchor_groups.append(ordered_anchor[: settings.source_anchor_slots])
        anchor_trace.append(
            {
                **result["anchor"].as_dict(),
                "versions": [str(v) for v in source_versions[result["anchor"].code]],
                "queries": result["queries"],
                "candidates": result["candidates"],
                "facet_filter": facet_filter,
                "selected": [str(parent_id) for parent_id in anchor_groups[-1]],
                "resolved": bool(anchor_groups[-1]),
            }
        )

    ordered_ids: list[uuid.UUID] = []
    if anchor_groups:
        ordered_ids.extend(
            uuid.UUID(chunk_id)
            for chunk_id in order_round_robin(
                [[str(parent_id) for parent_id in group] for group in anchor_groups],
                settings.source_anchor_slots,
            )
        )
    ordered_ids.extend(ordered_parent_ids)
    ordered_ids = list(dict.fromkeys(ordered_ids))

    evidence: list[Evidence] = []
    for parent_id in ordered_ids:
        item = item_by_parent.get(parent_id)
        if item is None:
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
                score=by_parent_id.get(parent.id, 0.0),
                species=normalize_species_list(doc.species),
                heading_path=list(parent.heading_path or []),
                graph_provenance=graph_provenance_by_child.get(str(child.id)),
            )
        )
        if len(evidence) >= (top_k or settings.max_sources):
            break

    requirements: list[Requirement] = []
    if modules["requirements"]:
        requirements = assess_requirements(
            build_requirements(query_ir),
            # A facet can be stated in the section heading rather than the
            # chunk body ("扣蟹培育" / "8.1水质指标"); the heading is part of
            # the evidence a human reader sees, so it counts for coverage.
            [f"{item.content}\n{' '.join(item.heading_path)}" for item in evidence],
        )
    gate = _assess_with_requirements(
        question,
        evidence,
        requirements,
        species_options,
        fallback_reason=None,
    )
    gate = _apply_current_regulation_gate(query_ir, gate)

    targeted_trace: dict | None = None
    # Generated once per request.  Recursive calls must not start a nested
    # loop, otherwise two gaps would trigger up to 2x2 retrievals.
    if (
        not gate.sufficient
        and modules["targeted"]
        and _attempt == 0
        and gate.reason not in TARGETED_SKIP_REASONS
    ):
        initial_reason = gate.reason
        targets = build_targeted_queries(
            question,
            requirements,
            gate.missing_terms,
            max_targets=settings.max_targeted_retrieval,
        )
        attempts: list[dict] = []
        for target in targets:
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
                search_question=target["query"],
                _attempt=_attempt + 1,
                # Return the raw pool: the outer loop re-gates the *merged*
                # evidence, so a retry that is insufficient on its own can
                # still contribute the one facet the first pass missed.
                keep_insufficient_evidence=True,
            )
            attempt = {
                "requirement": target["key"],
                "label": target["label"],
                "terms": target["terms"],
                "supplement": target["query"],
                "second_sufficient": second.sufficient,
                "second_gate_reason": (second.gate or {}).get("reason"),
                "added_sources": 0,
            }
            attempts.append(attempt)
            rankings = _merge_rankings(rankings, second.rankings)
            timings["targeted_ms"] = timings.get("targeted_ms", 0) + second.timings.get(
                "retrieval_ms", 0
            )
            merged = _merge_evidence(evidence, second.evidence) if second.evidence else []
            if not merged:
                continue
            added = max(0, len(merged) - len(evidence))
            merged = _covering_first(merged, target["terms"])
            evidence = merged[: settings.max_sources]
            for index, item in enumerate(evidence, start=1):
                item.source_index = index
            attempt["added_sources"] = added
            # Coverage flags are computed from the evidence set; the merged
            # set changed, so they must be re-assessed before the gate reads
            # them.  Without this the retry can add the missing facet and the
            # gate still refuses on the stale flag.
            requirements = assess_requirements(
                requirements,
                [f"{item.content}\n{' '.join(item.heading_path)}" for item in evidence],
            )
            gate = _assess_with_requirements(
                question,
                evidence,
                requirements,
                species_options,
                fallback_reason=None,
            )
            gate = _apply_current_regulation_gate(query_ir, gate)
            if gate.sufficient:
                break
        targeted_trace = {
            "mode": "requirement_targeted",
            "insufficient_reason": initial_reason,
            "targets": attempts,
            "sufficient_before": False,
            "sufficient_after": gate.sufficient,
        }

    if not gate.sufficient and not keep_insufficient_evidence:
        evidence = []

    if source_trace is not None:
        source_trace["anchors"] = anchor_trace
        source_trace["slots"] = settings.source_anchor_slots
        rankings["source_anchor"] = {
            entry["code"]: entry["selected"] for entry in anchor_trace
        }
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
        source_aware=source_trace,
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


def _apply_current_regulation_gate(query_ir, gate: Sufficiency) -> Sufficiency:
    """Refuse "latest/current" claims when no effective-date metadata exists.

    The index currently stores publication year, not an enforceable effective
    date or regulation status.  Lexical overlap with a document cannot prove
    that the list is the *current* one, so do not let such an answer through.
    """
    if query_ir is None or not getattr(query_ir, "requires_current_regulation", False):
        return gate
    if not gate.sufficient:
        return gate
    return Sufficiency(
        False,
        "current_regulation_unverified",
        gate.query_terms,
        gate.matched_terms,
        gate.matched_weight,
        gate.total_weight,
        gate.coverage,
        gate.best_index,
        gate.missing_terms,
    )


def _evidence_gate_text(item: Evidence) -> str:
    """Include provenance/heading terms without inventing content.

    A parent body may omit the section title (e.g. "8.1水质指标") that the user
    actually asked about.  Headings and title are source metadata, not generated
    text, so using them here fixes false ``weak_overlap`` refusals without
    lowering the gate thresholds.
    """
    return "\n".join(
        part
        for part in (
            item.title,
            " ".join(item.heading_path),
            item.quote,
            item.content,
        )
        if part
    )


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
        [_evidence_gate_text(item) for item in evidence],
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
    source_aware: dict | None = None,
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
        "source_aware_retrieval": source_aware
        or {"enabled": settings.enable_source_aware_retrieval},
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
