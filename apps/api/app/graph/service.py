"""Graph loading, entity linking, one-hop expansion, and graph-to-chunk lookup."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    GraphAlias,
    GraphEntity,
    GraphRelation,
    KbChunk,
    KbChunkEntity,
    KbDocument,
    KbDocumentVersion,
)
from app.species import GENERAL_SPECIES


@dataclass(slots=True)
class EntityData:
    id: uuid.UUID
    name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RelationData:
    source_id: uuid.UUID
    target_id: uuid.UUID
    relation_type: str
    provenance_version_id: uuid.UUID | None = None
    confidence: float = 1.0


@dataclass(slots=True)
class GraphData:
    entities: dict[uuid.UUID, EntityData]
    relations: list[RelationData]

    def terms(self) -> list[tuple[str, uuid.UUID]]:
        pairs: list[tuple[str, uuid.UUID]] = []
        for entity in self.entities.values():
            pairs.append((entity.name, entity.id))
            for alias in entity.aliases:
                pairs.append((alias, entity.id))
        return sorted(pairs, key=lambda item: len(item[0]), reverse=True)


@dataclass(slots=True)
class GraphExpansion:
    seed_entity_ids: list[uuid.UUID]
    expanded_entity_ids: list[uuid.UUID]
    seed_terms: list[str]
    expanded_terms: list[str]
    relation_trace: list[dict]
    max_hops: int = 1
    bidirectional: bool = False

    def as_dict(self) -> dict:
        return {
            "seed_entity_ids": [str(item) for item in self.seed_entity_ids],
            "expanded_entity_ids": [str(item) for item in self.expanded_entity_ids],
            "seed_terms": self.seed_terms,
            "expanded_terms": self.expanded_terms,
            "relation_trace": self.relation_trace,
            "max_hops": self.max_hops,
            "bidirectional": self.bidirectional,
        }


async def load_graph(db: AsyncSession) -> GraphData:
    entities = (await db.execute(select(GraphEntity))).scalars().all()
    aliases = (await db.execute(select(GraphAlias))).scalars().all()
    relations = (
        (await db.execute(select(GraphRelation).where(GraphRelation.review_status == "verified")))
        .scalars()
        .all()
    )
    by_id = {
        entity.id: EntityData(
            id=entity.id,
            name=entity.name,
            entity_type=entity.entity_type,
            aliases=[],
        )
        for entity in entities
    }
    for alias in aliases:
        if alias.entity_id in by_id and alias.review_status == "verified":
            by_id[alias.entity_id].aliases.append(alias.alias)
    return GraphData(
        entities=by_id,
        relations=[
            RelationData(
                source_id=relation.source_entity_id,
                target_id=relation.target_entity_id,
                relation_type=relation.relation_type,
                provenance_version_id=relation.provenance_document_version_id,
                confidence=relation.confidence,
            )
            for relation in relations
        ],
    )


def mention_entities(text: str, graph: GraphData) -> dict[uuid.UUID, int]:
    """Longest-match alias linking; no overlap accounting beyond one mention per term."""
    lowered = text.lower()
    counts: dict[uuid.UUID, int] = {}
    occupied: list[tuple[int, int]] = []
    for term, entity_id in graph.terms():
        needle = term.lower()
        start = lowered.find(needle)
        while start >= 0:
            end = start + len(needle)
            if not any(
                start < other_end and end > other_start for other_start, other_end in occupied
            ):
                occupied.append((start, end))
                counts[entity_id] = counts.get(entity_id, 0) + 1
            start = lowered.find(needle, start + 1)
    return counts


def expand_entities(
    question: str,
    graph: GraphData,
    max_related: int = 12,
    *,
    max_hops: int = 2,
    bidirectional: bool = True,
) -> GraphExpansion:
    """Expand verified graph relations up to ``max_hops`` with a path trace.

    The graph is intentionally small and only contains human-reviewed edges.
    Expansion is bounded both by ``max_related`` and by ``max_hops``; a path is
    recorded for every newly reached entity so the trace can be audited.  When
    ``bidirectional`` is true, reverse traversal is allowed (e.g. 浮头 -> 溶解氧
    -> 增氧), which is necessary for management questions expressed from the
    symptom side.
    """
    if max_hops < 1:
        raise ValueError("max_hops must be >= 1")
    mentions = mention_entities(question, graph)
    seed_ids = list(mentions)
    expanded = set(seed_ids)
    adjacency: dict[uuid.UUID, list[tuple[uuid.UUID, str, str, RelationData]]] = {}
    for relation in graph.relations:
        if relation.source_id not in graph.entities or relation.target_id not in graph.entities:
            continue
        adjacency.setdefault(relation.source_id, []).append(
            (relation.target_id, relation.relation_type, "forward", relation)
        )
        if bidirectional:
            adjacency.setdefault(relation.target_id, []).append(
                (relation.source_id, relation.relation_type, "reverse", relation)
            )

    def name(entity_id: uuid.UUID) -> str:
        return graph.entities[entity_id].name if entity_id in graph.entities else str(entity_id)

    paths: dict[uuid.UUID, list[uuid.UUID]] = {item: [item] for item in seed_ids}
    trace: list[dict] = []
    frontier = list(seed_ids)
    for hop in range(1, max_hops + 1):
        next_frontier: list[uuid.UUID] = []
        for source_id in frontier:
            for target_id, relation_type, direction, relation in adjacency.get(source_id, []):
                if target_id in expanded:
                    continue
                expanded.add(target_id)
                path = [*paths[source_id], target_id]
                paths[target_id] = path
                trace.append(
                    {
                        "source": name(source_id),
                        "target": name(target_id),
                        "relation_type": relation_type,
                        "direction": direction,
                        "hop": hop,
                        "path": [name(item) for item in path],
                        "path_entity_ids": [str(item) for item in path],
                        # Edge provenance: which document version asserted the
                        # relation and how confident the extractor was.
                        "provenance_version_id": (
                            str(relation.provenance_version_id)
                            if relation.provenance_version_id
                            else None
                        ),
                        "confidence": relation.confidence,
                    }
                )
                next_frontier.append(target_id)
                if len(expanded) >= len(seed_ids) + max_related:
                    break
            if len(expanded) >= len(seed_ids) + max_related:
                break
        frontier = next_frontier
        if not frontier or len(expanded) >= len(seed_ids) + max_related:
            break

    seed_terms = [graph.entities[item].name for item in seed_ids if item in graph.entities]
    expanded_terms = sorted(
        graph.entities[item].name
        for item in expanded
        if item in graph.entities and item not in seed_ids
    )
    return GraphExpansion(
        seed_entity_ids=seed_ids,
        expanded_entity_ids=sorted(expanded, key=lambda item: str(item)),
        seed_terms=seed_terms,
        expanded_terms=expanded_terms,
        relation_trace=trace,
        max_hops=max_hops,
        bidirectional=bidirectional,
    )


async def link_chunks(
    db: AsyncSession,
    chunks: list[tuple[uuid.UUID, str]],
    graph: GraphData,
) -> int:
    if not graph.entities or not chunks:
        return 0
    chunk_ids = [chunk_id for chunk_id, _ in chunks]
    await db.execute(delete(KbChunkEntity).where(KbChunkEntity.chunk_id.in_(chunk_ids)))
    rows = 0
    for chunk_id, content in chunks:
        for entity_id, count in mention_entities(content, graph).items():
            db.add(KbChunkEntity(chunk_id=chunk_id, entity_id=entity_id, mention_count=count))
            rows += 1
    await db.flush()
    return rows


async def graph_chunk_matches(
    db: AsyncSession,
    entity_ids: list[uuid.UUID],
    active_versions: list[uuid.UUID],
    *,
    category: str | None = None,
    species: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Return graph-linked chunks together with the entities that linked them.

    ``graph_chunk_ids`` throws the entity away, which makes a graph hit
    indistinguishable from an ordinary vector hit in the trace.  Keeping the
    matched entity ids is what lets the API expose provenance.
    """
    if not entity_ids or not active_versions:
        return []
    rows = (
        await db.execute(
            select(
                KbChunkEntity.chunk_id,
                KbChunkEntity.mention_count,
                KbChunkEntity.entity_id,
                KbDocument.species,
                KbDocument.category,
            )
            .join(KbChunk, KbChunk.id == KbChunkEntity.chunk_id)
            .join(KbDocumentVersion, KbDocumentVersion.id == KbChunk.document_version_id)
            .join(KbDocument, KbDocument.id == KbDocumentVersion.document_id)
            .where(
                KbChunkEntity.entity_id.in_(entity_ids),
                KbChunk.document_version_id.in_(active_versions),
                KbChunk.chunk_role == "child",
                KbDocument.status == "active",
            )
            .distinct()
        )
    ).all()
    ranked: dict[uuid.UUID, dict] = {}
    for chunk_id, count, entity_id, doc_species, doc_category in rows:
        if category and doc_category != category:
            continue
        if (
            species
            and species not in (doc_species or [])
            and GENERAL_SPECIES not in (doc_species or [])
        ):
            continue
        entry = ranked.setdefault(
            chunk_id, {"chunk_id": chunk_id, "entity_ids": set(), "mention_count": 0}
        )
        entry["entity_ids"].add(entity_id)
        entry["mention_count"] = max(entry["mention_count"], count)
    ordered = sorted(ranked.values(), key=lambda item: (-item["mention_count"], str(item["chunk_id"])))
    return [
        {
            "chunk_id": item["chunk_id"],
            "entity_ids": sorted(item["entity_ids"]),
            "mention_count": item["mention_count"],
        }
        for item in ordered[:limit]
    ]


async def graph_chunk_ids(
    db: AsyncSession,
    entity_ids: list[uuid.UUID],
    active_versions: list[uuid.UUID],
    *,
    category: str | None = None,
    species: str | None = None,
    limit: int = 10,
) -> list[uuid.UUID]:
    matches = await graph_chunk_matches(
        db,
        entity_ids,
        active_versions,
        category=category,
        species=species,
        limit=limit,
    )
    return [item["chunk_id"] for item in matches]
