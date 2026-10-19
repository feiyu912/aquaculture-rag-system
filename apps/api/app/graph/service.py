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

    def as_dict(self) -> dict:
        return {
            "seed_entity_ids": [str(item) for item in self.seed_entity_ids],
            "expanded_entity_ids": [str(item) for item in self.expanded_entity_ids],
            "seed_terms": self.seed_terms,
            "expanded_terms": self.expanded_terms,
            "relation_trace": self.relation_trace,
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


def expand_entities(question: str, graph: GraphData, max_related: int = 12) -> GraphExpansion:
    mentions = mention_entities(question, graph)
    seed_ids = list(mentions)
    expanded = set(seed_ids)
    trace: list[dict] = []
    for relation in graph.relations:
        if relation.source_id in seed_ids and relation.target_id not in expanded:
            expanded.add(relation.target_id)
            trace.append(
                {
                    "source": graph.entities[relation.source_id].name
                    if relation.source_id in graph.entities
                    else str(relation.source_id),
                    "target": graph.entities[relation.target_id].name
                    if relation.target_id in graph.entities
                    else str(relation.target_id),
                    "relation_type": relation.relation_type,
                }
            )
        if len(expanded) >= len(seed_ids) + max_related:
            break
    seed_terms = [graph.entities[item].name for item in seed_ids if item in graph.entities]
    expanded_terms = [
        graph.entities[item].name
        for item in expanded
        if item in graph.entities and item not in seed_ids
    ]
    return GraphExpansion(
        seed_entity_ids=seed_ids,
        expanded_entity_ids=sorted(expanded, key=lambda item: str(item)),
        seed_terms=seed_terms,
        expanded_terms=expanded_terms,
        relation_trace=trace,
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


async def graph_chunk_ids(
    db: AsyncSession,
    entity_ids: list[uuid.UUID],
    active_versions: list[uuid.UUID],
    *,
    category: str | None = None,
    species: str | None = None,
    limit: int = 10,
) -> list[uuid.UUID]:
    if not entity_ids or not active_versions:
        return []
    rows = (
        await db.execute(
            select(
                KbChunkEntity.chunk_id,
                KbChunkEntity.mention_count,
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
    ranked: dict[uuid.UUID, int] = {}
    for chunk_id, count, doc_species, doc_category in rows:
        if category and doc_category != category:
            continue
        if (
            species
            and species not in (doc_species or [])
            and GENERAL_SPECIES not in (doc_species or [])
        ):
            continue
        ranked[chunk_id] = max(ranked.get(chunk_id, 0), count)
    return [chunk_id for chunk_id, _ in sorted(ranked.items(), key=lambda item: -item[1])[:limit]]
