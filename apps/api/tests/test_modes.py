from __future__ import annotations

import pytest

from app.retrieval.service import normalize_mode


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid", "hybrid_rerank"])
def test_supported_modes(mode):
    assert normalize_mode(mode) == mode


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        normalize_mode("graphrag")
