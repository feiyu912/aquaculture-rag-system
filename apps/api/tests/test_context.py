from __future__ import annotations

from app.ingestion.context import build_context_text


def test_context_includes_title_heading_species_and_original():
    text = build_context_text(
        title="凡纳滨对虾养殖技术规范",
        heading_path=["第四章 养殖管理", "4.2 水质监测"],
        species=["凡纳滨对虾"],
        content="出现上述情况时，应增加监测频率。",
    )
    assert "文档：凡纳滨对虾养殖技术规范" in text
    assert "章节：第四章 养殖管理 / 4.2 水质监测" in text
    assert "适用品种：凡纳滨对虾" in text
    assert text.endswith("原文：\n出现上述情况时，应增加监测频率。")


def test_empty_species_defaults_to_general():
    text = build_context_text(
        title="通用水质资料", heading_path=None, species=[], content="溶解氧保持在 5 mg/L 以上。"
    )
    assert "适用品种：通用" in text
