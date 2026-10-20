from __future__ import annotations

import pytest

from app.generation.semantic_claims import verify_claims_semantic


class FakeEmbedder:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if ("甲壳" in text or "水温" in text) else [0.0, 1.0] for text in texts]


def test_semantic_screen_can_upgrade_lexical_unverified():
    claims = verify_claims_semantic(
        "甲壳动物需要保温 [S1]。",
        [{"index": 1, "quote": "适宜水温为18 ℃~21 ℃。"}],
        FakeEmbedder(),
        threshold=0.65,
    )
    assert claims[0]["lexical_status"] == "unverified"
    assert claims[0]["semantic_score"] == 1.0
    assert claims[0]["status"] == "supported"
    assert claims[0]["method"] == "bge_m3_cosine_v0"


def test_semantic_screen_does_not_upgrade_unrelated_claim():
    claims = verify_claims_semantic(
        "天气很好 [S1]。",
        [{"index": 1, "quote": "适宜水温为18 ℃~21 ℃。"}],
        FakeEmbedder(),
        threshold=0.65,
    )
    assert claims[0]["status"] == "unverified"
    assert claims[0]["lexical_status"] == "unverified"
    assert claims[0]["semantic_score"] == 0.0


def test_uncited_claim_remains_uncited():
    claims = verify_claims_semantic("没有引用的事实句。", [], FakeEmbedder())
    assert claims[0]["status"] == "uncited"
    assert "semantic_score" not in claims[0]


def test_embedder_vector_count_is_validated():
    class BrokenEmbedder:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0]]

    with pytest.raises(ValueError):
        verify_claims_semantic(
            "甲壳动物需要保温 [S1]。",
            [{"index": 1, "quote": "适宜水温为18 ℃~21 ℃。"}],
            BrokenEmbedder(),
        )
