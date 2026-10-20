#!/usr/bin/env python3
"""Resolve the human/AI-assisted seed labels to concrete chunk IDs.

The seed file stores document aliases and child ordinals, not UUIDs.  This
script reads the current active version and emits a stable JSONL dataset.  It
never calls an LLM and never changes labels; a missing chunk is a hard error.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import KbChunk, KbDocument, KbDocumentVersion

DOC_ALIASES = {
    "crab": "DB36_T 2225",
    "shrimp": "DB46 农产品全产业链",
}


async def build(seed_path: Path, out_path: Path) -> None:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    cases = seed["cases"]
    rows: list[str] = []
    async with SessionLocal() as db:
        docs = (
            (
                await db.execute(
                    select(KbDocument).where(
                        KbDocument.status == "active",
                        KbDocument.current_version_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_alias: dict[str, tuple[KbDocument, KbDocumentVersion]] = {}
        for alias, title_prefix in DOC_ALIASES.items():
            matches = [doc for doc in docs if doc.title.startswith(title_prefix)]
            if len(matches) != 1:
                raise SystemExit(
                    f"expected exactly one active document for {title_prefix!r}, got {len(matches)}"
                )
            doc = matches[0]
            version = await db.get(KbDocumentVersion, doc.current_version_id)
            if version is None:
                raise SystemExit(f"current version missing for {doc.title}")
            by_alias[alias] = (doc, version)

        chunk_cache: dict[tuple[str, int], KbChunk] = {}
        for alias, (doc, version) in by_alias.items():
            chunks = (
                (
                    await db.execute(
                        select(KbChunk).where(
                            KbChunk.document_version_id == version.id,
                            KbChunk.chunk_role == "child",
                        )
                    )
                )
                .scalars()
                .all()
            )
            for chunk in chunks:
                chunk_cache[(alias, chunk.ordinal)] = chunk

        for case in cases:
            gold = []
            for item in case.get("gold") or []:
                alias = item["doc"]
                ordinal = int(item["ordinal"])
                chunk = chunk_cache.get((alias, ordinal))
                if chunk is None:
                    raise SystemExit(f"{case['id']}: missing {alias} child ordinal {ordinal}")
                doc, version = by_alias[alias]
                page = (chunk.locations or [{}])[0].get("page") or chunk.page_from
                gold.append(
                    {
                        "document_id": str(doc.id),
                        "version_id": str(version.id),
                        "title": doc.title,
                        "page": page,
                        "chunk_id": str(chunk.id),
                        "parent_chunk_id": str(chunk.parent_id) if chunk.parent_id else None,
                        "grade": int(item.get("grade", 2)),
                        "evidence": chunk.content[:520].replace("\n", " "),
                    }
                )
            if not gold and not case.get("expect_insufficient"):
                raise SystemExit(f"{case['id']}: answerable case has no gold")
            pages = sorted({item["page"] for item in gold})
            titles = sorted({item["title"] for item in gold})
            row = {
                **case,
                "gold": gold,
                "gold_pages": pages,
                "gold_titles": titles,
                "gold_title": titles[0] if len(titles) == 1 else None,
                "gold_chunk_ids": [item["chunk_id"] for item in gold],
                "review_required": True,
            }
            rows.append(json.dumps(row, ensure_ascii=False))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    manifest = {
        "dataset": seed.get("dataset"),
        "version": seed.get("version"),
        "cases": len(rows),
        "answerable": sum(not json.loads(line)["expect_insufficient"] for line in rows),
        "sha256": digest,
        "seed": str(seed_path.relative_to(ROOT))
        if seed_path.is_relative_to(ROOT)
        else str(seed_path),
        "annotation_status": "ai_assisted_pending_human_review",
        "note": "gold chunk IDs resolved from the active DB version; review before publication",
    }
    manifest_path = out_path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"wrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=Path, default=ROOT / "eval" / "real_questions_v1.seed.json")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "real_questions_v1.jsonl")
    args = parser.parse_args()
    asyncio.run(build(args.seed, args.out))


if __name__ == "__main__":
    main()
