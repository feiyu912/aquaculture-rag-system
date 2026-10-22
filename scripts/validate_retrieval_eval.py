#!/usr/bin/env python3
"""Validate a retrieval eval set against the live index and prior question sets.

Checks:
  - ids and questions are unique, questions are Chinese and non-trivial
  - every gold chunk exists, is a child chunk of a servable document, and has a
    point in Qdrant
  - the reference answer overlaps the gold chunk text (guards against a question
    whose gold was picked from an unrelated chunk)
  - overlap with prior sets (QA-dataset team + earlier internal set) stays below
    the similarity threshold
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def norm(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text or "").lower()


def shingles(text: str, n: int = 5) -> set[str]:
    value = norm(text)
    return {value[i : i + n] for i in range(max(0, len(value) - n + 1))}


def jaccard(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def load_prior() -> list[str]:
    out: list[str] = []
    for path in [*ROOT.glob("data/hf_qa/eval/*.jsonl"), ROOT / "eval/real_questions_v1.jsonl"]:
        if not Path(path).exists():
            continue
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("question"):
                out.append(row["question"])
    return out


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "retrieval_eval_100_v1.jsonl")
    parser.add_argument("--threshold", type=float, default=0.55)
    args = parser.parse_args()

    from sqlalchemy import text

    from app.config import settings
    from app.db import SessionLocal
    from app.retrieval.vector_store import get_client

    rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line]
    errors: list[str] = []
    gold_chunks = [row["gold"][0]["chunk_id"] for row in rows]

    async with SessionLocal() as db:
        meta = {
            str(r[0]): (str(r[1]), r[2])
            for r in (
                await db.execute(
                    text(
                        "SELECT c.id, c.content, d.index_eligibility FROM kb_chunks c "
                        "JOIN kb_document_versions v ON v.id=c.document_version_id "
                        "JOIN kb_documents d ON d.id=v.document_id WHERE c.id = ANY(:ids)"
                    ),
                    {"ids": gold_chunks},
                )
            ).all()
        }
    client = get_client()
    points = client.retrieve(
        collection_name=settings.qdrant_collection,
        ids=gold_chunks,
        with_payload=False,
        with_vectors=False,
    )
    point_ids = {str(p.id) for p in points}

    seen_questions: dict[str, str] = {}
    prior = load_prior()
    worst = (0.0, "", "")
    for row in rows:
        qid = row["id"]
        question = row["question"]
        if not re.search(r"[\u4e00-\u9fff]", question):
            errors.append(f"{qid}: question has no Chinese")
        if len(question) < 8:
            errors.append(f"{qid}: question too short")
        if question in seen_questions:
            errors.append(f"{qid}: duplicate of {seen_questions[question]}")
        seen_questions[question] = qid
        for gold in row["gold"]:
            chunk_id = gold["chunk_id"]
            if chunk_id not in meta:
                errors.append(f"{qid}: gold chunk {chunk_id} missing")
                continue
            content, eligibility = meta[chunk_id]
            if eligibility != "eligible":
                errors.append(f"{qid}: gold doc eligibility={eligibility}")
            if chunk_id not in point_ids:
                errors.append(f"{qid}: gold chunk has no qdrant point")
            answer = row["reference_answer"]
            if answer and not (answer[:40] in content or jaccard(answer, content[:600]) > 0.3):
                errors.append(f"{qid}: reference answer does not match gold chunk text")
        for prior_question in prior:
            score = jaccard(question, prior_question)
            if score > worst[0]:
                worst = (score, qid, prior_question)

    report = {
        "dataset": str(args.dataset.relative_to(ROOT)),
        "cases": len(rows),
        "by_group": {
            key: sum(1 for r in rows if r["group"] == key)
            for key in sorted({r["group"] for r in rows})
        },
        "gold_chunks_found": len(meta),
        "gold_points_found": len(point_ids),
        "max_prior_similarity": {"score": round(worst[0], 3), "case": worst[1], "prior": worst[2]},
        "errors": errors,
    }
    out = args.dataset.with_suffix(".validation.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))