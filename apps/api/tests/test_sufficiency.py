from __future__ import annotations

from app.retrieval.sufficiency import assess_evidence


def test_in_domain_question_passes_with_aggregate_evidence():
    result = assess_evidence(
        "中华绒螯蟹养殖对溶解氧有什么要求？",
        [
            "中华绒螯蟹喜欢水质清新、溶氧充足的环境。",
            "溶解氧：保持在 5 mg/L 以上，低氧时需及时增氧。",
        ],
    )
    assert result.sufficient
    assert result.matched_terms == ["中华绒螯蟹", "溶解氧"]


def test_out_of_domain_question_is_rejected():
    result = assess_evidence(
        "今天上海天气怎么样？",
        ["日常监测记录表中包含天气、水温和采样时间。"],
    )
    assert not result.sufficient
    assert result.reason == "weak_overlap"
    assert result.matched_terms == ["天气"]


def test_single_domain_term_is_valid():
    result = assess_evidence("溶解氧", ["溶解氧保持在 5 mg/L 以上。"])
    assert result.sufficient


def test_single_generic_term_is_not_valid():
    result = assess_evidence("天气", ["记录天气和水温。"])
    assert not result.sufficient


def test_abbreviation_matches_full_species_name():
    result = assess_evidence("对虾盐度要求", ["凡纳滨对虾养殖需要关注盐度。"])
    assert result.sufficient
    assert "对虾" in result.matched_terms


def test_no_evidence_fails():
    result = assess_evidence("溶解氧", [])
    assert not result.sufficient
    assert result.reason == "no_evidence"
