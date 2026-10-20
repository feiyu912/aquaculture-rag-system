from __future__ import annotations

from app.query.ir import build_query_ir
from app.query.router import select_modules


def test_semantic_route_enables_graph_only():
    ir = build_query_ir("DO 偏低时怎么办？", [])
    assert ir.strategy == "semantic_expansion"
    modules = select_modules(
        ir, graph=False, decomposition=False, requirements=False, targeted=False
    )
    assert modules["graph"] is True
    assert modules["decomposition"] is False


def test_multihop_route_enables_graph_and_decomposition():
    ir = build_query_ir("先看溶解氧，然后分析氨氮，最后给出处理方案", [])
    assert ir.strategy == "multi_hop"
    modules = select_modules(
        ir, graph=False, decomposition=False, requirements=False, targeted=False
    )
    assert modules["graph"] is True
    assert modules["decomposition"] is True


def test_plain_route_keeps_explicit_switches():
    ir = build_query_ir("中华绒螯蟹对溶解氧有什么要求？", ["中华绒螯蟹"])
    modules = select_modules(
        ir, graph=False, decomposition=True, requirements=False, targeted=False
    )
    assert modules["graph"] is False
    assert modules["decomposition"] is True
