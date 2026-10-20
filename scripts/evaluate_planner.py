"""Compare rule IR and LLM planner IR on a small author-labelled probe set.

The labels are engineering acceptance checks, not human qrels.  The script
measures structured understanding only; it deliberately makes no claim about
answer quality or retrieval recall.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings
from app.generation.llm import build_generator
from app.query.ir import build_query_ir
from app.query.planner import planner_from_generator

DEFAULT_OPTIONS = ["通用", "中华绒螯蟹", "凡纳滨对虾"]
FIELDS = ["species", "growth_stage", "water_parameters", "diseases"]


def _set(value: object) -> set[str]:
    if not value:
        return set()
    return {str(item).strip() for item in value if str(item).strip()}  # type: ignore[union-attr]


def _prf(predicted: set[str], expected: set[str]) -> tuple[float, float, float]:
    if not predicted and not expected:
        return 1.0, 1.0, 1.0
    tp = len(predicted & expected)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _score(ir, expected: dict) -> dict:
    scores: dict[str, float] = {}
    for field in FIELDS:
        expected_set = _set(expected.get(field))
        predicted = _set(getattr(ir, field))
        scores[field] = _prf(predicted, expected_set)[2]
    expected_intent = expected.get("intent")
    scores["intent"] = float(ir.intent == expected_intent) if expected_intent else 1.0
    scored = [
        scores[field] for field in [*FIELDS, "intent"] if field != "intent" or expected_intent
    ]
    scores["field_accuracy"] = sum(scored) / len(scored)
    scores["hard_filter"] = float(ir.species_filter == expected.get("hard_filter"))
    scores["subquestions"] = float(
        len(ir.planner_subquestions) >= int(expected.get("subquestions_min", 0))
    )
    if expected.get("requested_year") is not None:
        scores["year"] = float(ir.requested_year == expected["requested_year"])
    return scores


def _public(ir) -> dict:
    return {
        "intent": ir.intent,
        "species": ir.species,
        "growth_stage": ir.growth_stage,
        "water_parameters": ir.water_parameters,
        "diseases": ir.diseases,
        "species_filter": ir.species_filter,
        "requested_year": ir.requested_year,
        "planner_source": ir.planner_source,
        "planner_subquestions": ir.planner_subquestions,
        "planner_tasks": ir.planner_tasks,
        "planner_constraints": ir.planner_constraints,
        "warnings": ir.warnings,
    }


async def run(probes: list[dict], options: list[str], out: Path, metadata: dict) -> dict:
    generator = build_generator()
    planner = planner_from_generator(generator)
    if planner is None:
        raise SystemExit("generator does not expose complete()")
    metadata["planner_model"] = getattr(generator, "name", type(generator).__name__)
    metadata["planner_max_tokens"] = settings.planner_max_tokens
    metadata["planner_timeout_s"] = settings.planner_timeout_s
    details = []
    for probe in probes:
        question = probe["question"]
        expected = probe["expected"]
        rule_ir = build_query_ir(question, options)
        started = time.perf_counter()
        outcome = await planner.plan(question, rule_ir, options)
        elapsed = (time.perf_counter() - started) * 1000
        details.append(
            {
                "id": probe["id"],
                "question": question,
                "expected": expected,
                "rule": _public(rule_ir),
                "rule_score": _score(rule_ir, expected),
                "llm": _public(outcome.ir),
                "llm_score": _score(outcome.ir, expected),
                "planner": outcome.trace(),
                "wall_ms": round(elapsed, 1),
            }
        )
        print(
            f"{probe['id']} rule={details[-1]['rule_score']['field_accuracy']:.2f} "
            f"llm={details[-1]['llm_score']['field_accuracy']:.2f} "
            f"used={outcome.used_llm} err={outcome.error}",
            flush=True,
        )

    def aggregate(key: str, family: str) -> float:
        return round(statistics.mean(item[key][family] for item in details), 4)

    summary = {
        **metadata,
        "probe_count": len(details),
        "rule_field_accuracy": aggregate("rule_score", "field_accuracy"),
        "llm_field_accuracy": aggregate("llm_score", "field_accuracy"),
        "rule_hard_filter_accuracy": aggregate("rule_score", "hard_filter"),
        "llm_hard_filter_accuracy": aggregate("llm_score", "hard_filter"),
        "rule_subquestion_ok": aggregate("rule_score", "subquestions"),
        "llm_subquestion_ok": aggregate("llm_score", "subquestions"),
        "llm_used_rate": round(
            sum(1 for item in details if item["planner"]["used_llm"]) / len(details), 4
        ),
        "llm_fallback_count": sum(1 for item in details if item["planner"]["error"]),
        "avg_wall_ms": round(statistics.mean(item["wall_ms"] for item in details), 1),
        "annotation_status": "author_engineering_probes_not_human_qrels",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "planner_probes_details.json").write_text(
        json.dumps({"summary": summary, "details": details}, ensure_ascii=False, indent=2) + "\n"
    )
    (out / "planner_probes_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probes", type=Path, default=ROOT / "eval" / "planner_probes_v1.json")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "runs" / "planner_probes_v1")
    parser.add_argument("--limit", type=int, default=0, help="debug: only run the first N probes")
    args = parser.parse_args()
    probes = json.loads(args.probes.read_text())
    if args.limit > 0:
        probes = probes[: args.limit]
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "probes_sha256": hashlib.sha256(args.probes.read_bytes()).hexdigest(),
        "planner_model": None,
        "planner_max_tokens": None,
        "planner_timeout_s": None,
    }
    asyncio.run(run(probes, DEFAULT_OPTIONS, args.out, metadata))


if __name__ == "__main__":
    main()
