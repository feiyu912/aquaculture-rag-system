#!/usr/bin/env python3
"""Lexical citation-support audit for generated answers.

For every answer sentence that carries citation markers, measure how much of the
sentence's character 4-gram content is present in the cited parent chunk(s).
This is a proxy for "the citation supports the sentence", not entailment; a
human must still read the sampled answers before the number goes in the thesis.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
CITE = re.compile(r"\[S?(\d+)\]")


def grams(text: str, n: int = 4) -> set[str]:
    clean = re.sub(r"[\s\W_]+", "", text)
    return {clean[i : i + n] for i in range(max(0, len(clean) - n + 1))}


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[。；！？\n])", text) if s.strip()]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, default=ROOT / "eval" / "runs" / "answer_quality_50")
    args = parser.parse_args()

    from sqlalchemy import text

    from app.db import SessionLocal

    details = [
        json.loads(line)
        for line in (args.run / "details.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    ids = {
        pid
        for row in details
        for pid in (row.get("rules") or {}).get("evidence_parent_ids", [])
    }
    async with SessionLocal() as db:
        contents = {
            str(r[0]): r[1]
            for r in (
                await db.execute(
                    text("SELECT id::text, content FROM kb_chunks WHERE id = ANY(:ids)"),
                    {"ids": list(ids)},
                )
            ).all()
        }

    totals: Counter = Counter()
    per_case = []
    for row in details:
        record = row.get("rules") or {}
        answer = record.get("answer") or ""
        parents = record.get("evidence_parent_ids") or []
        cited = supported = 0
        unsupported_examples = []
        uncited_facts = 0
        for sentence in sentences(answer):
            markers = [int(value) for value in CITE.findall(sentence)]
            if markers:
                cited += 1
                reference = " ".join(
                    contents.get(parents[m - 1], "") for m in markers if 0 < m <= len(parents)
                )
                score = len(grams(sentence) & grams(reference)) / max(1, len(grams(sentence)))
                if score >= 0.35:
                    supported += 1
                else:
                    unsupported_examples.append({"sentence": sentence[:120], "overlap": round(score, 3)})
            elif re.search(r"\d|应|宜|需|必须|不得|禁止", sentence) and len(sentence) >= 12:
                uncited_facts += 1
        per_case.append(
            {
                "id": row["id"],
                "answered": record.get("answered"),
                "sufficient": record.get("sufficient"),
                "answer_chars": record.get("answer_chars", 0),
                "citation_coverage": record.get("citation_coverage", 0),
                "cited_sentences": cited,
                "supported_sentences": supported,
                "support_rate": round(supported / cited, 3) if cited else 0.0,
                "uncited_fact_sentences": uncited_facts,
                "invalid_citations": record.get("invalid_citations", []),
                "unsupported_examples": unsupported_examples[:3],
            }
        )
        totals["cases"] += 1
        totals["answered"] += 1 if record.get("answered") else 0
        totals["cited"] += cited
        totals["supported"] += supported
        totals["uncited_facts"] += uncited_facts
        totals["invalid_cases"] += 1 if record.get("invalid_citations") else 0

    summary = {
        "cases": totals["cases"],
        "answered": totals["answered"],
        "citation_coverage_mean": round(
            sum(c["citation_coverage"] for c in per_case) / len(per_case), 4
        ),
        "cited_sentences": totals["cited"],
        "supported_sentences": totals["supported"],
        "support_rate": round(totals["supported"] / totals["cited"], 4) if totals["cited"] else 0.0,
        "uncited_fact_sentences": totals["uncited_facts"],
        "cases_with_invalid_citation": totals["invalid_cases"],
        "method": "character 4-gram overlap between cited sentence and cited parent chunk; "
        ">=0.35 counted as supported. Proxy only, not entailment.",
    }
    (args.run / "citation_analysis.json").write_text(
        json.dumps({"summary": summary, "cases": per_case}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))