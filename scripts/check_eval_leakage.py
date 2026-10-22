#!/usr/bin/env python3
"""Detect evaluation-set leakage into the knowledge base.

Three independent checks, each with a different failure consequence:

1. **exact** — normalised eval question equals a FAQ question.
2. **near-duplicate** — character 3-gram Jaccard >= 0.8.
3. **answer overlap** — character 3-gram Jaccard between the eval reference
   answer and the FAQ answer >= 0.7.

Severity depends on where the FAQ lives:

* ``verified`` / ``indexed``  -> **CRITICAL**. The model can retrieve the answer
  to a test question, so every metric on that question is meaningless.
* ``pending``                 -> **WARNING**. Not retrievable today, but must be
  excluded from promotion or the leak becomes critical later.

Any ``usage_scope="eval"`` row that is verified or indexed is always critical.

Exit code is 1 when at least one critical finding exists, so CI can gate on it.

Usage:
    uv run python ../../scripts/check_eval_leakage.py
    uv run python ../../scripts/check_eval_leakage.py --threshold 0.7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import FaqEntry  # noqa: E402

PUNCT = "，。！？；：、（）【】《》“”‘’…—·,.!?;:()[]<>\"'`~ "


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in value if ch not in PUNCT)


def trigrams(text: str) -> set[str]:
    value = normalize(text)
    if len(value) < 3:
        return {value} if value else set()
    return {value[i : i + 3] for i in range(len(value) - 2)}


def jaccard(a: str, b: str) -> float:
    left, right = trigrams(a), trigrams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def load_eval_questions(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    rows = []
    for case in cases or []:
        if not isinstance(case, dict):
            continue
        question = (case.get("question") or "").strip()
        if not question:
            continue
        rows.append(
            {
                "id": case.get("id"),
                "question": question,
                "reference_answer": (case.get("reference_answer") or "").strip(),
            }
        )
    return rows


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--eval", default=str(ROOT / "eval" / "real_questions_v1.seed.json")
    )
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--answer-threshold", type=float, default=0.7)
    parser.add_argument(
        "--report", default=str(ROOT / "data" / "reports" / "eval_leakage_report.json")
    )
    args = parser.parse_args()

    await init_db()
    eval_rows = load_eval_questions(Path(args.eval))

    async with SessionLocal() as db:
        faqs = (await db.execute(select(FaqEntry))).scalars().all()

    critical: list[dict] = []
    warnings: list[dict] = []
    mitigated: list[dict] = []
    exact = near = answer_hits = 0

    for entry in faqs:
        normalized_faq_question = normalize(entry.question)
        for case in eval_rows:
            normalized_eval = normalize(case["question"])
            kind = None
            score = 0.0
            if normalized_faq_question == normalized_eval:
                kind, score = "exact_question", 1.0
            else:
                score = jaccard(case["question"], entry.question)
                if score >= args.threshold:
                    kind = "near_duplicate_question"
                elif case["reference_answer"]:
                    answer_score = jaccard(case["reference_answer"], entry.answer)
                    if answer_score >= args.answer_threshold:
                        kind, score = "answer_overlap", answer_score
            if kind is None:
                continue

            if kind == "exact_question":
                exact += 1
            elif kind == "near_duplicate_question":
                near += 1
            else:
                answer_hits += 1

            indexed = entry.indexed_at is not None
            verified = entry.review_status == "verified"
            is_eval_scope = entry.usage_scope == "eval"
            finding = {
                "eval_id": case["id"],
                "eval_question": case["question"],
                "faq_id": str(entry.id),
                "faq_question": entry.question,
                "kind": kind,
                "score": round(score, 3),
                "review_status": entry.review_status,
                "usage_scope": entry.usage_scope,
                "indexed": indexed,
            }
            if entry.review_status == "rejected":
                finding["severity"] = "mitigated"
                finding["reason"] = "rejected FAQ duplicates an evaluation question"
                mitigated.append(finding)
            elif is_eval_scope and (indexed or verified):
                finding["severity"] = "critical"
                finding["reason"] = "usage_scope=eval row is verified/indexed"
                critical.append(finding)
            elif verified or indexed:
                finding["severity"] = "critical"
                finding["reason"] = "verified FAQ duplicates an evaluation question"
                critical.append(finding)
            else:
                finding["severity"] = "warning"
                finding["reason"] = "pending FAQ duplicates an evaluation question"
                warnings.append(finding)

        # A eval-scoped row must never be indexed, even without a duplicate.
        if entry.usage_scope == "eval" and (entry.indexed_at is not None or entry.review_status == "verified"):
            critical.append(
                {
                    "eval_id": None,
                    "faq_id": str(entry.id),
                    "faq_question": entry.question,
                    "kind": "eval_scope_activated",
                    "severity": "critical",
                    "reason": "usage_scope=eval must never be verified or indexed",
                }
            )

    report = {
        "at": datetime.now(UTC).isoformat(),
        "eval_questions": len(eval_rows),
        "faq_entries": len(faqs),
        "thresholds": {
            "question_jaccard": args.threshold,
            "answer_jaccard": args.answer_threshold,
        },
        "summary": {
            "exact": exact,
            "near_duplicate": near,
            "answer_overlap": answer_hits,
            "critical": len(critical),
            "warnings": len(warnings),
            "mitigated": len(mitigated),
        },
        "critical": critical,
        "warnings": warnings,
        "mitigated": mitigated,
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"eval_questions={len(eval_rows)} faq_entries={len(faqs)} "
        f"exact={exact} near={near} answer_overlap={answer_hits}"
    )
    print(f"critical={len(critical)} warnings={len(warnings)} -> {path}")
    for item in critical[:10]:
        print(f"  CRITICAL {item['kind']} [{item['score']}] {item['faq_question'][:42]}")
    for item in warnings[:5]:
        print(f"  WARN     {item['kind']} [{item['score']}] {item['faq_question'][:42]}")
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))