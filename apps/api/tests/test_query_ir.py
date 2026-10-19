from __future__ import annotations

from app.query.ir import build_query_ir, compile_constraints, route_query

OPTIONS = ["通用", "中华绒螯蟹", "凡纳滨对虾"]


def test_exact_species_becomes_hard_filter():
    ir = build_query_ir("中华绒螯蟹养殖对溶解氧有什么要求？", OPTIONS)
    assert ir.species == ["中华绒螯蟹"]
    assert ir.species_filter == "中华绒螯蟹"
    assert ir.water_parameters == ["溶解氧"]
    assert "溶解氧" in ir.normalized_question


def test_ambiguous_species_does_not_become_hard_filter():
    ir = build_query_ir("中华绒螯蟹和凡纳滨对虾的盐度要求", OPTIONS)
    assert set(ir.species) == {"中华绒螯蟹", "凡纳滨对虾"}
    assert ir.species_filter is None
    assert "multiple_species_no_hard_filter" in ir.warnings


def test_unique_suffix_alias_is_allowed():
    ir = build_query_ir("对虾养殖的盐度要求", ["通用", "凡纳滨对虾"])
    assert ir.species == ["凡纳滨对虾"]
    assert ir.species_filter == "凡纳滨对虾"
    assert ir.strategy == "semantic_expansion"


def test_year_is_not_compiled_as_published_year_filter():
    ir = build_query_ir("2026 年最新规范里凡纳滨对虾的用药限制", OPTIONS)
    assert ir.intent == "regulation"
    assert ir.requested_year == 2026
    assert ir.requires_current_regulation
    assert "published_year" in ir.unsupported_constraints
    assert "effective_date" in ir.unsupported_constraints
    compiled = compile_constraints(ir)
    assert compiled.species == "凡纳滨对虾"
    # No unsupported date/status constraint may leak into a hard filter.
    assert compiled.category is None


def test_explicit_species_overrides_text_detection():
    ir = build_query_ir("盐度要求", OPTIONS, explicit_species="凡纳滨对虾")
    assert ir.species_filter == "凡纳滨对虾"


def test_explicit_category_is_preserved_but_not_inferred():
    ir = build_query_ir("氨氮范围", OPTIONS, explicit_category="水质管理")
    assert ir.category_filter == "水质管理"
    assert build_query_ir("氨氮范围", OPTIONS).category_filter is None


def test_route_is_deterministic():
    ir = build_query_ir("中华绒螯蟹蜕壳期溶解氧偏低且摄食下降，应该检查什么？", OPTIONS)
    assert route_query(ir) == ir.strategy
