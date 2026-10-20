from __future__ import annotations

from app.query.sources import (
    SourceAnchor,
    extract_source_anchors,
    facet_covered,
    matches_title,
    order_round_robin,
)


def test_extracts_literal_standard_codes_in_order():
    anchors = extract_source_anchors(
        "DB36 和 DB46 两个标准对养殖水体溶解氧的最低要求是否一致？"
    )
    assert [anchor.code for anchor in anchors] == ["DB36", "DB46"]
    assert anchors[0].position < anchors[1].position


def test_extracts_recommended_standard_forms():
    assert [a.code for a in extract_source_anchors("GB/T 11607 与 SC/T 1132 的规定")] == [
        "GB11607",
        "SC1132",
    ]
    assert [a.code for a in extract_source_anchors("DB32/T 5292—2025 生态育苗")] == ["DB32"]


def test_deduplicates_and_limits_sources():
    anchors = extract_source_anchors("DB36、DB36、DB46、DB32、GB 11607", limit=3)
    assert [anchor.code for anchor in anchors] == ["DB36", "DB46", "DB32"]


def test_ignores_placeholders_and_non_codes():
    # The placeholder year (XXXX) is ignored, but the code DB46 is real.
    assert [a.code for a in extract_source_anchors("DB 46/T XXXX—XXXX")] == ["DB46"]
    # "GB/T1.1" must not become GB1 (single-digit section numbers are not codes).
    assert extract_source_anchors("按照 GB/T1.1-2020 起草") == []
    assert extract_source_anchors("2026 年养殖水质") == []


def test_match_title_handles_both_code_spellings():
    db36 = SourceAnchor(code="DB36", raw="DB36", position=0)
    db46 = SourceAnchor(code="DB46", raw="DB46", position=0)
    assert matches_title("DB36_T 2225—2026 中华绒螯蟹池塘培育扣蟹技术规程", db36)
    assert matches_title("DB 36/T 2225—2026 中华绒螯蟹", db36)
    assert matches_title("DB46 农产品全产业链生产规范 南美白对虾", db46)
    assert not matches_title("DB360 其它标准", db36)
    assert not matches_title("DB32_T 5292—2025 中华绒螯蟹生态育苗技术规范", db46)


def test_facet_coverage_uses_document_wording():
    assert facet_covered("8.1水质指标溶氧量5mg/L以上", ["溶解氧"])
    assert facet_covered("溶解氧含量保持5 mg/L以上", ["溶解氧"])
    assert facet_covered("pH值7.5~8.5", ["酸碱度"])
    assert not facet_covered("9.3水环境要求水温20℃~33℃", ["溶解氧"])
    assert facet_covered("任何文本", [])


def test_round_robin_keeps_every_cited_source_early():
    assert order_round_robin([["a1", "a2"], ["b1"]], slots=2) == ["a1", "b1", "a2"]
    assert order_round_robin([["a1"], ["b1"], ["c1"]], slots=2) == ["a1", "b1", "c1"]
    assert order_round_robin([], slots=2) == []
    assert order_round_robin([["a1", "a1"]], slots=2) == ["a1"]


def test_source_aware_defaults_are_enabled_without_touching_gate_thresholds():
    from app.config import settings

    assert settings.enable_source_aware_retrieval is True
    assert settings.source_anchor_slots == 2
    # The evidence gate thresholds must stay at their conservative values.
    assert settings.evidence_min_terms == 2
    assert settings.evidence_min_weight == 3.0
    assert settings.evidence_min_coverage == 0.3