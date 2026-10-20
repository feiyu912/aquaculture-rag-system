#!/usr/bin/env python3
"""Compare deterministic rule IR with the optional LLM query planner.

These are hand-labelled planning checks, not retrieval metrics and not a claim
that either planner is generally better.  Run with the real configured LLM only
when the API key is available; otherwise use ``--mode rule``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.config import settings
from app.generation.llm import build_generator
from app.query.ir import QueryIR, build_query_ir
from app.query.planner import LLMQueryPlanner

SPECIES_OPTIONS = ["通用", "中华绒螯蟹", "凡纳滨对虾"]


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    species_filter: str | None
    water: set[str]
    stage: set[str]
    intent: str
    review: str = "human_confirmed"


CASES = [
    Case(
        id="Q001",
        question="中华绒螯蟹蜕壳期对溶解氧有什么要求？",
        species_filter="中华绒螯蟹",
        water={"溶解氧"},
        stage={"蜕壳期"},
        intent="complex",
    ),
    Case(
        id="Q002",
        question="凡纳滨对虾养殖前期氨氮和亚硝酸盐如何控制？",
        species_filter="凡纳滨对虾",
        water={"氨氮", "亚硝酸盐"},
        stage={"养殖前期"},
        intent="complex",
    ),
    Case(
        id="Q003",
        question="高温期pH偏高对中华绒螯蟹有什么影响？",
        species_filter="中华绒螯蟹",
        water={"酸碱度"},
        stage={"高温期"},
        intent="complex",
    ),
    Case(
        id="Q004",
        question="DB36 标准对中华绒螯蟹扣蟹培育的溶氧要求是什么？",
        species_filter="中华绒螯蟹",
        water={"溶解氧"},
        stage=set(),
        intent="regulation",
    ),
    Case(
        id="Q005",
        question="氨氮过高怎么处理？",
        species_filter=None,
        water={"氨氮"},
        stage=set(),
        intent="fact",
    ),
]


def _score(ir: QueryIR, case: Case) -> dict[str, Any]:
    water = set(ir.water_parameters)
    stage = set(ir.growth_stage)
    return {
        "species_ok": ir.species_filter == case.species_filter,
        "water_recall": len(case.water & water) / len(case.water)
        if case.water
        else 1.0,
        "water_precision": len(case.water & water) / len(water) if water else 1.0,
        "stage_recall": len(case.stage & stage) / len(case.stage)
        if case.stage
        else 1.0,
        "intent_ok": ir.intent == case.intent,
        "species_filter": ir.species_filter,
        "water_parameters": sorted(water),
        "growth_stage": sorted(stage),
        "intent": ir.intent,
        "subquestions": ir.planner_subquestions,
    }


async def run(mode: str, out: Path) -> None:
    results: list[dict[str, Any]] = []
    planner = None
    if mode in {"llm", "both"}:
        generator = build_generator()
        planner = LLMQueryPlanner(generator)
        if not hasattr(generator, "complete"):
            raise SystemExit("configured LLM generator cannot run planner completions")

    for case in CASES:
        rule = build_query_ir(
            case.question,
            SPECIES_OPTIONS,
            explicit_species=case.species_filter,
        )
        if mode == "rule":
            ir, trace = rule, None
        else:
            assert planner is not None
            outcome = await planner.plan(case.question, rule, SPECIES_OPTIONS)
            ir, trace = outcome.ir, outcome.trace()
        results.append(
            {
                "id": case.id,
                "question": case.question,
                "review_status": case.review,
                "expected": {
                    "species_filter": case.species_filter,
                    "water": sorted(case.water),
                    "stage": sorted(case.stage),
                    "intent": case.intent,
                },
                "rule": _score(rule, case),
                "llm": _score(ir, case) if mode != "rule" else None,
                "trace": trace,
            }
        )

    summary: dict[str, Any] = {
        "mode": mode,
        "provider": settings.llm_provider,
        "cases": len(results),
    }
    for key in (
        "species_ok",
        "water_recall",
        "water_precision",
        "stage_recall",
        "intent_ok",
    ):
        summary[key] = round(
            sum(
                float(item["llm" if mode != "rule" else "rule"][key])
                for item in results
            )
            / len(results),
            3,
        )
    payload = {"summary": summary, "results": results}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for item in results:
        rule = item["rule"]
        print(
            f"{item['id']}: RULE species={rule['species_filter']} water={rule['water_parameters']} "
            f"stage={rule['growth_stage']} intent={rule['intent']}"
        )
        if item["llm"]:
            llm = item["llm"]
            print(
                f"      LLM  species={llm['species_filter']} water={llm['water_parameters']} "
                f"stage={llm['growth_stage']} intent={llm['intent']} "
                f"used={item['trace']['used_llm']} attempts={item['trace']['attempts']} "
                f"error={item['trace']['error']}"
            )
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["rule", "llm", "both"], default="rule")
    parser.add_argument(
        "--out", type=Path, default=Path("reports/query-planner-comparison.json")
    )
    args = parser.parse_args()
    asyncio.run(run(args.mode, args.out))


if __name__ == "__main__":
    main()
