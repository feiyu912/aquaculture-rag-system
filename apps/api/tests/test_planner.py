from __future__ import annotations

import json

import pytest

from app.query.ir import build_query_ir
from app.query.planner import (
    LLMQueryPlanner,
    PlannerIR,
    merge_plan,
    parse_planner_json,
    should_use_llm_planner,
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


def test_planner_builds_typed_tasks_with_declared_inheritance():
    payload = {
        "intent": "complex",
        "species": ["中华绒螯蟹"],
        "growth_stage": ["蜕壳期"],
        "water_parameters": ["溶解氧", "氨氮"],
        "subquestions": [
            {
                "question": "氨氮要求是什么？",
                "facet": "水质",
                "inherits": ["species", "growth_stage"],
            },
            {
                "question": "需要怎么增氧？",
                "facet": "管理",
                "inherits": ["species"],
            },
        ],
        "confidence": 0.8,
    }
    ir = merge_plan(
        "中华绒螯蟹蜕壳期对溶解氧和氨氮有什么要求？",
        PlannerIR.model_validate(payload),
        build_query_ir("中华绒螯蟹蜕壳期对溶解氧和氨氮有什么要求？", OPTIONS),
        OPTIONS,
    )
    first, second = ir.planner_tasks
    assert first["inherited_constraints"] == {
        "species": ["中华绒螯蟹"],
        "growth_stage": ["蜕壳期"],
    }
    assert first["effective_query"].startswith("中华绒螯蟹 蜕壳期")
    assert "水温" not in second["effective_query"]
    assert second["inherited_constraints"] == {"species": ["中华绒螯蟹"]}
    assert first["source"] == "llm"


def test_non_species_hard_constraint_is_downgraded():
    payload = {
        "intent": "complex",
        "species": ["中华绒螯蟹"],
        "constraints": [
            {
                "name": "water_temperature",
                "value": "20",
                "source": "explicit",
                "strength": "hard",
            }
        ],
        "confidence": 0.8,
    }
    ir = merge_plan(
        "中华绒螯蟹水温 20 度时怎么管理？",
        PlannerIR.model_validate(payload),
        build_query_ir("中华绒螯蟹水温 20 度时怎么管理？", OPTIONS),
        OPTIONS,
    )
    assert ir.planner_constraints[0]["accepted_as_hard"] is False
    assert ir.planner_constraints[0]["scope"] == "soft_context"
    assert "llm_constraint_not_implemented_as_hard" in ir.warnings


def test_unknown_inherits_field_is_rejected():
    with pytest.raises(ValueError):
        parse_planner_json(
            '{"intent":"complex","subquestions":[{"question":"子问题","inherits":["bogus"]}]}'
        )


def test_subquestion_does_not_inherit_sibling_stage_when_it_names_one():
    payload = {
        "intent": "complex",
        "species": ["中华绒螯蟹"],
        "growth_stage": ["生态育苗", "扣蟹培育"],
        "water_parameters": ["水温", "酸碱度"],
        "subquestions": [
            {
                "question": "中华绒螯蟹生态育苗对水温和pH的要求是什么？",
                "inherits": ["species", "growth_stage", "water_parameters"],
            }
        ],
        "confidence": 0.8,
    }
    ir = merge_plan(
        "中华绒螯蟹生态育苗和扣蟹培育对水温和pH的要求分别是什么？",
        PlannerIR.model_validate(payload),
        build_query_ir("中华绒螯蟹生态育苗和扣蟹培育对水温和pH的要求分别是什么？", OPTIONS),
        OPTIONS,
    )
    task = ir.planner_tasks[0]
    assert "扣蟹培育" not in task["effective_query"]
    assert task["inherited_constraints"] == {}


@pytest.mark.asyncio
async def test_planner_timeout_falls_back_to_rules(monkeypatch):
    import asyncio

    from app.config import settings

    class SlowCompleter:
        async def complete(self, *args, **kwargs):
            await asyncio.sleep(1.0)
            return "{}"

    monkeypatch.setattr(settings, "planner_timeout_s", 0.01)
    planner = LLMQueryPlanner(SlowCompleter())
    outcome = await planner.plan("中华绒螯蟹对溶解氧有什么要求？", _rule_ir(), OPTIONS)
    assert outcome.used_llm is False
    assert outcome.ir.planner_source == "rules"
    assert "TimeoutError" in (outcome.error or "")


def test_planner_is_skipped_for_single_facet_fact():
    assert should_use_llm_planner(build_query_ir("溶解氧是什么？", OPTIONS)) is False
    complex_ir = build_query_ir("中华绒螯蟹生态育苗和扣蟹培育对水温和pH的要求分别是什么？", OPTIONS)
    assert should_use_llm_planner(complex_ir) is True


@pytest.mark.asyncio
async def test_planner_retries_empty_content_with_larger_budget():
    class EmptyThenValid:
        def __init__(self):
            self.calls = 0
            self.max_tokens = []

        async def complete(self, *args, max_tokens=900, **kwargs):
            self.calls += 1
            self.max_tokens.append(max_tokens)
            if self.calls == 1:
                raise RuntimeError("openai_compatible returned empty content")
            return '{"intent":"fact","species":[],"confidence":0.5}'

    completer = EmptyThenValid()
    outcome = await LLMQueryPlanner(completer).plan(
        "中华绒螯蟹对溶解氧有什么要求？", _rule_ir(), OPTIONS
    )
    assert outcome.used_llm is True
    assert completer.calls == 2
    assert completer.max_tokens[1] > completer.max_tokens[0]


def test_subquestion_with_inferred_species_is_flagged_not_hard_filtered():
    payload = {
        "intent": "complex",
        "species": ["中华绒螯蟹"],
        "growth_stage": ["扣蟹培育"],
        "subquestions": [
            {
                "question": "中华绒螯蟹扣蟹培育阶段氨氮超标怎么处理？",
                "inherits": ["species", "growth_stage"],
            }
        ],
        "confidence": 0.7,
    }
    ir = merge_plan(
        "扣蟹培育阶段氨氮超标怎么处理？",
        PlannerIR.model_validate(payload),
        build_query_ir("扣蟹培育阶段氨氮超标怎么处理？", OPTIONS),
        OPTIONS,
    )
    assert ir.species_filter is None
    assert ir.planner_tasks[0]["unverified_species_in_text"] == ["中华绒螯蟹"]
    assert "llm_subquestion_added_unverified_species" in ir.warnings


def test_comparison_marker_triggers_planner_even_with_one_facet():
    ir = build_query_ir("DB36 和 DB46 对溶解氧下限的要求是否一致？", OPTIONS)
    assert should_use_llm_planner(ir) is True
