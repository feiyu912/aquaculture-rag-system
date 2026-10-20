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


def test_contextual_index_hash_is_separate_from_raw_index(monkeypatch):
    from app.config import settings
    from app.ingestion.pipeline import chunk_config_hash

    monkeypatch.setattr(settings, "enable_contextual_retrieval", False)
    raw_hash = chunk_config_hash()
    monkeypatch.setattr(settings, "enable_contextual_retrieval", True)
    context_hash = chunk_config_hash()
    assert raw_hash != context_hash


def test_heading_path_drops_body_like_segments():
    from app.ingestion.context import sanitize_heading_path

    cleaned = sanitize_heading_path(
        [
            "中华绒螯蟹生态育苗技术规范",
            "100 mg/L 的漂白粉处理池水。挂笼前，抱卵蟹用8.0 mg/L 苯扎溴铵溶液药浴2 h。",
            "6.4水质控制",
        ]
    )
    assert cleaned == ["中华绒螯蟹生态育苗技术规范", "6.4水质控制"]


def test_context_does_not_embed_body_like_heading_noise():
    text = build_context_text(
        title="DB32/T 5292—2025",
        heading_path=["中华绒螯蟹生态育苗技术规范", "100 mg/L 的漂白粉处理池水。", "6.4水质控制"],
        species=["中华绒螯蟹"],
        content="适宜水温为18 ℃~21 ℃。",
    )
    assert "100 mg/L" not in text
    assert "章节：中华绒螯蟹生态育苗技术规范 / 6.4水质控制" in text


def test_chunker_sanitizes_heading_path_for_new_chunks():
    import uuid

    from app.ingestion.chunker import build_chunks
    from app.ingestion.parser import ParsedBlock, ParsedDocument

    def block(text: str, level: int = 0) -> ParsedBlock:
        return ParsedBlock(
            page=1,
            bbox=[10, 700, 500, 720],
            text=text,
            page_width=595,
            page_height=842,
            heading_level=level,
        )

    parsed = ParsedDocument(
        page_count=1,
        blocks=[
            block("中华绒螯蟹生态育苗技术规范", level=1),
            block("100 mg/L 的漂白粉处理池水。", level=2),
            block("6.4水质控制", level=3),
            block("适宜水温为18 ℃~21 ℃。"),
        ],
    )
    chunks = build_chunks(parsed, uuid.uuid4(), parent_target=200, child_target=80, overlap=10)
    assert chunks
    for chunk in chunks:
        assert "100 mg/L" not in " / ".join(chunk.heading_path)
        assert "6.4水质控制" in chunk.heading_path
