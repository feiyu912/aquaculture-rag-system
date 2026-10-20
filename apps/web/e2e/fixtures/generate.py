#!/usr/bin/env python3
"""Generate deterministic PDF fixtures for the end-to-end suite.

The fixtures are intentionally simple so that the test can predict where a
citation should land:

* ``e2e-3page.pdf``   three pages, each with an ASCII marker line
* ``e2e-rotated.pdf`` page 2 carries ``/Rotate 90``
* ``e2e-3page-v2.pdf`` revised content, used for the version-update flow
* ``e2e-single.pdf``  one page, used for quick upload checks

Run with:  uv run python apps/web/e2e/fixtures/generate.py
"""
from __future__ import annotations

import pathlib

import pymupdf

OUT = pathlib.Path(__file__).resolve().parent

A4 = pymupdf.paper_rect("a4")
W, H = A4.width, A4.height  # 595.28 x 841.89


def _page(doc: pymupdf.Document, text: str, marker: str, marker_y: float) -> None:
    page = doc.new_page(width=W, height=H)
    page.insert_text((60, 80), text, fontsize=20, fontname="china-s")
    page.insert_text((60, 120), marker, fontsize=14, fontname="helv")
    page.insert_text((60, marker_y), f"{marker} BODY LINE", fontsize=11, fontname="helv")
    page.insert_text(
        (60, marker_y + 20),
        f"{marker} SECOND LINE OF THE SAME BLOCK",
        fontsize=11,
        fontname="helv",
    )
    page.draw_rect(pymupdf.Rect(55, marker_y - 16, W - 55, marker_y + 34), color=(0.8, 0.8, 0.8))


def build_3page() -> pymupdf.Document:
    doc = pymupdf.open()
    _page(doc, "端到端测试文档 第一页", "E2E-P1", 300)
    _page(doc, "端到端测试文档 第二页", "E2E-P2", 420)
    _page(doc, "端到端测试文档 第三页", "E2E-P3", 540)
    return doc


def build_single() -> pymupdf.Document:
    doc = pymupdf.open()
    _page(doc, "端到端测试文档 单页", "E2E-S1", 360)
    return doc


def build_v2() -> pymupdf.Document:
    doc = pymupdf.open()
    _page(doc, "端到端测试文档 第一页 修订版", "E2E-P1", 300)
    _page(doc, "端到端测试文档 第二页 修订版", "E2E-P2", 420)
    _page(doc, "端到端测试文档 第三页 修订版", "E2E-P3", 540)
    return doc


def build_rotated() -> pymupdf.Document:
    doc = pymupdf.open()
    _page(doc, "旋转测试 第一页", "E2E-R1", 300)
    page = _rotated_page(doc, "旋转测试 第二页（页面旋转 90 度）", "E2E-R2", 420)
    page.set_rotation(90)
    return doc


def _rotated_page(doc: pymupdf.Document, text: str, marker: str, marker_y: float):
    page = doc.new_page(width=W, height=H)
    page.insert_text((60, 80), text, fontsize=20, fontname="china-s")
    page.insert_text((60, 120), marker, fontsize=14, fontname="helv")
    page.insert_text((60, marker_y), f"{marker} ROTATED BODY", fontsize=11, fontname="helv")
    return page


def main() -> None:
    for name, builder in (
        ("e2e-3page.pdf", build_3page),
        ("e2e-single.pdf", build_single),
        ("e2e-3page-v2.pdf", build_v2),
        ("e2e-rotated.pdf", build_rotated),
    ):
        doc = builder()
        target = OUT / name
        doc.save(target, garbage=4, deflate=True)
        doc.close()
        print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
