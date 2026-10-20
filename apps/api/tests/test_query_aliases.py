from __future__ import annotations

from app.query.expand import alias_variants
from app.query.ir import build_query_ir


def test_dissolved_oxygen_alias_variant_is_added():
    question = "中华绒螯蟹对溶解氧有什么要求？"
    ir = build_query_ir(question, ["中华绒螯蟹"])
    variants = alias_variants(question, ir)
    assert any("溶氧量" in variant for variant in variants)
    assert variants


def test_aliases_do_not_invent_terms_for_generic_question():
    question = "今天上海天气怎么样？"
    ir = build_query_ir(question, [])
    assert alias_variants(question, ir) == []


def test_variant_limit_is_respected():
    ir = build_query_ir("中华绒螯蟹对溶解氧和酸碱度有什么要求？", ["中华绒螯蟹"])
    variants = alias_variants("中华绒螯蟹对溶解氧和酸碱度有什么要求？", ir, limit=2)
    assert len(variants) <= 2
