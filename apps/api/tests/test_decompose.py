from __future__ import annotations

from app.query.decompose import decompose_question
from app.query.ir import build_query_ir


def test_multiple_parameters_produce_facet_queries_with_species():
    ir = build_query_ir("中华绒螯蟹对溶解氧和氨氮有什么要求？", ["中华绒螯蟹"])
    variants = decompose_question("中华绒螯蟹对溶解氧和氨氮有什么要求？", ir)
    assert len(variants) == 2
    assert all("中华绒螯蟹" in item for item in variants)
    assert any("溶解氧" in item for item in variants)
    assert any("氨氮" in item for item in variants)


def test_split_conjunction_keeps_original_out():
    variants = decompose_question("养殖池塘如何增氧？同时如何控制氨氮？", None)
    assert len(variants) == 2
    assert all("养殖池塘" in item or "氨氮" in item for item in variants)


def test_single_facet_has_no_decomposition():
    assert decompose_question("中华绒螯蟹对溶解氧有什么要求？", None) == []
