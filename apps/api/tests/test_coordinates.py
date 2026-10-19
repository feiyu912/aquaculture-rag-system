from __future__ import annotations

import pymupdf

from app.ingestion.parser import ParsedBlock, PyMuPDFParser


def test_canonical_bbox_converts_top_left_to_bottom_left():
    crop = pymupdf.Rect(0, 0, 200, 800)
    bbox = PyMuPDFParser._canonical_bbox((10, 20, 110, 60), crop)
    assert bbox == [10, 740, 110, 780]


def test_canonical_bbox_respects_cropbox_offset():
    crop = pymupdf.Rect(20, 30, 220, 830)
    bbox = PyMuPDFParser._canonical_bbox((30, 50, 130, 90), crop)
    assert bbox == [10, 740, 110, 780]


def test_location_declares_origin_and_units():
    block = ParsedBlock(
        page=4,
        bbox=[120, 422, 500, 502],
        text="x",
        page_width=595,
        page_height=842,
        rotation=0,
    )
    loc = block.location()
    assert loc["coordinate_system"] == "pdf_points"
    assert loc["origin"] == "bottom-left"
    assert loc["page_width"] == 595
    assert loc["page"] == 4
