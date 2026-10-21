#!/usr/bin/env python3
"""Recompute nDCG from saved rankings with the corrected scorer.

The pre-2026-10-21 scorer dropped irrelevant items before computing DCG, which
re-ranked relevant items from position 1 and overestimated nDCG.  This script
does not re-run retrieval; it reuses ``ranked_*`` and ``gold`` fields already
stored in ``eval/runs`` so the correction is auditable against the old numbers.

Usage:
    python3 scripts/recompute_ndcg.py
    python3 scripts/recompute_ndcg.py --out eval/runs/ndcg_recompute.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.evaluation.retrieval_metrics import score_ranking

KEYS = ("ndcg@5", "ndcg@10")


def mean(rows: list[float]) -> float:
    return round(statistics.mean(rows), 4) if rows else 0.0


def recompute_details(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.get("mode", "unknown"), []).append(row)

    result = []
    for mode, subset in grouped.items():
        answerable = [row for row in subset if not row.get("expect_insufficient")]
        for label, group in (("all", subset), ("answerable", answerable)):
            if not group:
                continue
            old = {key: mean([row.get(key, 0.0) for row in group]) for key in KEYS}
            new = {key: mean([score_ranking(row["ranked_chunk_ids"], row["gold"], ks=(5, 10))[key] for row in group]) for key in KEYS}
            result.append(
                {
                    "run": path.parent.name,
                    "mode": mode,
                    "denominator": label,
                    "cases": len(group),
                    "old": old,
                    "new": new,
                    "delta": {key: round(new[key] - old[key], 4) for key in KEYS},
                }
            )
    return result


def recompute_planner_ab(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    details = data.get("details") or data
    result = []
    for family in ("rules", "llm"):
        for label in ("all", "answered"):
            group = [row for row in details if label == "all" or row[family].get("sufficient")]
            if not group:
                continue
            old = {key: mean([row[family]["metrics"].get(key, 0.0) for row in group]) for key in KEYS}
            new = {
                key: mean(
                    [
                        score_ranking(row[family]["ranked_parent_ids"], row["gold"], ks=(5, 10))[key]
                        for row in group
                    ]
                )
                for key in KEYS
            }
            result.append(
                {
                    "run": path.name,
                    "mode": family,
                    "denominator": label,
                    "cases": len(group),
                    "old": old,
                    "new": new,
                    "delta": {key: round(new[key] - old[key], 4) for key in KEYS},
                }
            )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "runs" / "ndcg_recompute.json")
    parser.add_argument(
        "--planner-ab",
        type=Path,
        default=ROOT / "eval" / "runs" / "planner_retrieval_ab_70_v5.json",
    )
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for path in sorted((ROOT / "eval" / "runs").glob("*/details.jsonl")):
        first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        if "ranked_chunk_ids" in first and "gold" in first:
            rows.extend(recompute_details(path))
    if args.planner_ab.exists():
        rows.extend(recompute_planner_ab(args.planner_ab))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    header = f"{'run':38} {'mode':13} {'denom':10} {'n':>3}  {'nDCG@5 old':>10} {'new':>7}  {'nDCG@10 old':>11} {'new':>7}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['run'][:38]:38} {row['mode'][:13]:13} {row['denominator']:10} {row['cases']:>3}  "
            f"{row['old']['ndcg@5']:>10.4f} {row['new']['ndcg@5']:>7.4f}  "
            f"{row['old']['ndcg@10']:>11.4f} {row['new']['ndcg@10']:>7.4f}"
        )
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()