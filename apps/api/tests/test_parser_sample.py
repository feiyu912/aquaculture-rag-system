from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.parser import PyMuPDFParser

SAMPLE = Path(__file__).resolve().parents[3] / "data" / "samples" / "aquaculture_sample.pdf"


@pytest.mark.skipif(not SAMPLE.exists(), reason="run scripts/make_sample_pdf.py first")
def test_sample_pdf_has_pages_tables_and_valid_bboxes():
    parsed = PyMuPDFParser().parse(SAMPLE)
    assert parsed.page_count == 4
    assert parsed.blocks
    assert any(block.block_type == "table" for block in parsed.blocks)
    for block in parsed.blocks:
        x0, y0, x1, y1 = block.bbox
        assert 0 <= x0 < x1 <= block.page_width + 0.5
        assert 0 <= y0 < y1 <= block.page_height + 0.5
        assert block.text.strip()
