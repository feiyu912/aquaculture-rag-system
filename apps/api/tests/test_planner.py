from __future__ import annotations

import json

import pytest

from app.query.ir import build_query_ir
from app.query.planner import (
    LLMQueryPlanner,
    PlannerIR,
    merge_plan,
    parse_planner_json,
)
from app.retrieval.service import _inherit_constraints

OPTIONS = ["通用", "中华绒螯蟹", "凡纳滨对虾"]


class _FakeCompleter:
    def __init__(self, payload: dict | str):
        self.payload = payload
        self.calls = 0

    async def complete(self, messages, *, max_tokens=900, temperature=0.0, response_format=None):
        self.calls += 1
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload, ensure_ascii=False)


def _rule_ir():
    return build_query_ir("中华绒螯蟹对溶解氧有什么要求？", OPTIONS)


def test_planner_merges_explicit_and_marks_inferred_species_soft():
    payload = {
        "intent": "complex",
        "species": ["凡纳滨对虾"],
        "water_parameters": ["DO"],
        "constraints": [
            {"name": "species", "value": "凡纳滨对虾", "source": "inferred", "strength": "hard"},
            {"name": "species", "value": "中华绒螯蟹", "source": "explicit", "strength": "hard"},
        ],
        "assumptions": ["用户可能同时关心对虾"],
        "subquestions": [
            {"question": "溶解氧要求是什么？", "facet": "水质", "inherits": ["species"]}
        ],
        "confidence": 0.8,
    }
    ir = merge_plan(
        "中华绒螯蟹对溶解氧有什么要求？", PlannerIR.model_validate(payload), _rule_ir(), OPTIONS
    )
    assert ir.species_filter == "中华绒螯蟹"  # rule-derived hard filter wins
    assert ir.planner_source == "llm"
    assert "llm_inferred_species_not_hard_filter" in ir.warnings
    assert any(
        item["source"] == "inferred" and item["accepted_as_hard"] is False
        for item in ir.planner_constraints
    )
    assert ir.water_parameters == ["溶解氧"]
    assert ir.planner_subquestions == ["溶解氧要求是什么？"]


@pytest.mark.asyncio
async def test_planner_accepts_valid_json_and_traces():
    payload = {
        "intent": "fact",
        "species": ["中华绒螯蟹"],
        "water_parameters": ["溶解氧"],
        "subquestions": [],
        "confidence": 0.9,
    }
    planner = LLMQueryPlanner(_FakeCompleter(payload))
    outcome = await planner.plan("中华绒螯蟹对溶解氧有什么要求？", _rule_ir(), OPTIONS)
    assert outcome.used_llm is True
    assert outcome.plan is not None
    assert outcome.ir.planner_source == "llm"
    assert outcome.trace()["used_llm"] is True


@pytest.mark.asyncio
async def test_planner_invalid_json_falls_back_to_rules():
    planner = LLMQueryPlanner(_FakeCompleter("not json"))
    outcome = await planner.plan("中华绒螯蟹对溶解氧有什么要求？", _rule_ir(), OPTIONS)
    assert outcome.used_llm is False
    assert outcome.ir.planner_source == "rules"
    assert "invalid JSON" in (outcome.error or "")


def test_planner_rejects_extra_schema_fields():
    with pytest.raises(ValueError):
        parse_planner_json('{"intent":"fact","unexpected":true}')


def test_subquestion_inherits_species_and_stage():
    ir = build_query_ir("中华绒螯蟹蜕壳期对溶解氧和氨氮有什么要求？", OPTIONS)
    inherited = _inherit_constraints("氨氮要求是什么？", ir)
    assert "中华绒螯蟹" in inherited
    assert "蜕壳期" in inherited
