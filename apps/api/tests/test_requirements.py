from __future__ import annotations

from app.query.ir import build_query_ir
from app.retrieval.requirements import (
    assess_requirements,
    build_requirements,
    build_supplemental_query,
    missing_terms,
)


def _ir(question: str):
    return build_query_ir(question, ["中华绒螯蟹", "凡纳滨对虾", "通用"])


def test_two_water_parameters_create_two_requirements():
    ir = _ir("中华绒螯蟹对溶解氧和氨氮有什么要求？")
    requirements = build_requirements(ir)
    assert [item.terms for item in requirements] == [["溶解氧"], ["氨氮"]]


def test_missing_parameter_is_reported_and_used_for_supplement():
    ir = _ir("中华绒螯蟹对溶解氧和氨氮有什么要求？")
    requirements = assess_requirements(build_requirements(ir), ["溶解氧应保持在 5 mg/L 以上"])
    assert missing_terms(requirements) == ["氨氮"]
    supplement = build_supplemental_query("中华绒螯蟹对溶解氧和氨氮有什么要求？", requirements, [])
    assert supplement is not None
    assert "氨氮" in supplement


def test_out_of_domain_question_does_not_trigger_retry():
    ir = _ir("今天上海天气怎么样？")
    requirements = assess_requirements(build_requirements(ir), [])
    assert build_supplemental_query("今天上海天气怎么样？", requirements, ["天气"]) is None
