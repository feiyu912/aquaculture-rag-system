from __future__ import annotations

from app.ingestion.parser import _heading_level


def test_quantity_lines_are_not_headings():
    assert (
        _heading_level(
            "100 mg/L 的漂白粉处理池水。挂笼前，抱卵蟹用8.0 mg/L 苯扎溴铵溶液药浴2 h。", 10, 10
        )
        == 0
    )
    assert _heading_level("5 mg/L", 10, 10) == 0
    assert _heading_level("2026 年 10 月", 10, 10) == 0


def test_numbered_section_headings_are_kept():
    assert _heading_level("4.3水质要求", 10, 10) == 3
    assert _heading_level("4 土池及养殖条件", 10, 10) == 2
    assert _heading_level("8.1水质指标", 10, 10) == 3
