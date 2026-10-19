"""Seed the small verified graph and backfill entity mentions for active chunks."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.db import SessionLocal, engine, init_db
from app.graph.seed import SEED_ENTITIES, SEED_RELATIONS
from app.graph.service import link_chunks, load_graph
from app.models import (
    GraphAlias,
    GraphEntity,
    GraphRelation,
    KbChunk,
    KbDocument,
    KbDocumentVersion,
)


async def main() -> None:
    await init_db()
    async with SessionLocal() as db:
        by_name: dict[str, GraphEntity] = {}
        for spec in SEED_ENTITIES:
            entity = (
                await db.execute(select(GraphEntity).where(GraphEntity.name == spec["name"]))
            ).scalar_one_or_none()
            if entity is None:
                entity = GraphEntity(
                    name=spec["name"],
                    entity_type=spec["entity_type"],
                    review_status="verified",
                )
                db.add(entity)
                await db.flush()
            by_name[spec["name"]] = entity
            for alias in spec["aliases"]:
                existing = (
                    await db.execute(select(GraphAlias).where(GraphAlias.alias == alias))
                ).scalar_one_or_none()
                if existing is None:
                    db.add(
                        GraphAlias(
                            entity_id=entity.id,
                            alias=alias,
                            review_status="verified",
                        )
                    )
        for source_name, target_name, relation_type in SEED_RELATIONS:
            source = by_name.get(source_name)
            target = by_name.get(target_name)
            if source is None or target is None:
                continue
            existing = (
                await db.execute(
                    select(GraphRelation).where(
                        GraphRelation.source_entity_id == source.id,
                        GraphRelation.target_entity_id == target.id,
                        GraphRelation.relation_type == relation_type,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    GraphRelation(
                        source_entity_id=source.id,
                        target_entity_id=target.id,
                        relation_type=relation_type,
                        confidence=1.0,
                        review_status="verified",
                    )
                )
        await db.commit()

        graph = await load_graph(db)
        chunks = (
            await db.execute(
                select(KbChunk.id, KbChunk.content)
                .join(KbDocumentVersion, KbDocumentVersion.id == KbChunk.document_version_id)
                .join(KbDocument, KbDocument.id == KbDocumentVersion.document_id)
                .where(
                    KbChunk.chunk_role == "child",
                    KbDocument.status == "active",
                    KbDocument.current_version_id == KbDocumentVersion.id,
                )
            )
        ).all()
        rows = await link_chunks(db, [(chunk_id, content) for chunk_id, content in chunks], graph)
        await db.commit()
        print(
            f"graph seeded: {len(graph.entities)} entities, {len(graph.relations)} relations, "
            f"{len(chunks)} chunks scanned, {rows} mention links"
        )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
