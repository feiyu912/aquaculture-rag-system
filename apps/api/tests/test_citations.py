from __future__ import annotations

from app.generation.citations import parse_citations, validate_answer


def test_parse_variants_and_dedupe():
    text = "结论一 [S1]，结论二 [1]，结论三【2】，组合 [S1,S3]。"
    assert parse_citations(text) == [1, 2, 3]


def test_valid_citation_and_coverage():
    text = "溶解氧应保持在 5 mg/L 以上 [S1]。日常巡塘需要观察水色。"
    report = validate_answer(text, max_index=2)
    assert report.valid
    assert report.invalid_indices == []
    assert report.factual_sentences == 2
    assert report.cited_factual == 1
    assert report.coverage == 0.5


def test_invalid_citation_is_reported_not_dropped():
    text = "南美白对虾适合在任意盐度养殖 [S9]。"
    report = validate_answer(text, max_index=2)
    assert not report.valid
    assert report.invalid_indices == [9]


def test_missing_citation_reduces_coverage():
    text = "溶解氧应保持在 5 mg/L 以上。氨氮宜控制在 0.2 mg/L 以下 [S1]。"
    report = validate_answer(text, max_index=2)
    assert report.factual_sentences == 2
    assert report.cited_factual == 1
    assert report.coverage == 0.5


def test_year_like_bracket_is_invalid():
    text = "资料发布于 [2024]。"
    report = validate_answer(text, max_index=2)
    assert report.invalid_indices == [2024]
