from __future__ import annotations

import uuid

from app.ingestion.chunker import build_chunks
from app.ingestion.parser import ParsedBlock, ParsedDocument


def _block(text: str, page: int = 1, level: int = 0, kind: str = "text") -> ParsedBlock:
    return ParsedBlock(
        page=page,
        bbox=[10, 700, 500, 720],
        text=text,
        page_width=595,
        page_height=842,
        block_type=kind,
        heading_level=level,
        font_size=14 if level else 10,
    )


def test_parent_child_and_heading_path():
    parsed = ParsedDocument(
        page_count=1,
        blocks=[
            _block("一、水质管理", level=2),
            _block("溶解氧应保持在 5 mg/L 以上。"),
            _block("低氧时开启增氧机。"),
        ],
    )
    chunks = build_chunks(parsed, uuid.uuid4(), parent_target=200, child_target=30, overlap=5)
    parents = [c for c in chunks if c.role == "parent"]
    children = [c for c in chunks if c.role == "child"]
    assert len(parents) == 1
    assert children
    assert parents[0].content.startswith("一、水质管理")
    assert parents[0].heading_path == ["一、水质管理"]
    assert all(child.parent_id == parents[0].id for child in children)


def test_table_is_its_own_parent():
    parsed = ParsedDocument(
        page_count=1,
        blocks=[
            _block("五、监测记录", level=2),
            _block("| 日期 | 溶解氧 |\n| --- | --- |\n| 1 | 6.2 |", kind="table"),
        ],
    )
    chunks = build_chunks(parsed, uuid.uuid4())
    parents = [c for c in chunks if c.role == "parent"]
    tables = [c for c in parents if c.block_type == "table"]
    assert len(tables) == 1
    assert tables[0].content.startswith("| 日期 |")
    assert tables[0].heading_path == ["五、监测记录"]


def test_heading_only_group_is_not_emitted():
    parsed = ParsedDocument(
        page_count=1,
        blocks=[_block("六、术语", level=2), _block("| a | b |", kind="table")],
    )
    chunks = build_chunks(parsed, uuid.uuid4())
    parents = [c for c in chunks if c.role == "parent"]
    assert all(c.content.strip() not in {"六、术语"} for c in parents)


def test_locations_merge_per_page():
    parsed = ParsedDocument(
        page_count=2,
        blocks=[
            _block("第一页内容第一段。", page=1),
            _block("第一页内容第二段。", page=1),
            _block("第二页内容。", page=2),
        ],
    )
    chunks = build_chunks(parsed, uuid.uuid4())
    parent = next(c for c in chunks if c.role == "parent")
    assert len(parent.locations) == 2
    assert parent.page_from == 1
    assert parent.page_to == 2
