from __future__ import annotations

from app.query.ir import build_query_ir
from app.retrieval.service import route_block_reason


def test_calculation_route_blocks_without_tool():
    ir = build_query_ir("生石灰用量怎么计算？", [])
    assert ir.strategy == "calculation"
    assert route_block_reason(ir) == "calculation_tool_unavailable"


def test_current_regulation_blocks_without_effective_date_metadata():
    ir = build_query_ir("2026年现行水产养殖用药规范是什么？", [])
    assert ir.strategy == "regulation"
    assert route_block_reason(ir) == "regulation_metadata_unavailable"


def test_simple_fact_route_has_no_block():
    ir = build_query_ir("中华绒螯蟹对溶解氧有什么要求？", ["中华绒螯蟹"])
    assert route_block_reason(ir) is None
