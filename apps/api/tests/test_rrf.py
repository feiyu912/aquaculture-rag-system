from __future__ import annotations

from app.retrieval.rrf import rrf_fuse


def test_rrf_prefers_document_in_both_lists():
    fused = rrf_fuse([["a", "b"], ["b", "c"]], k=60)
    ids = [doc_id for doc_id, _ in fused]
    assert ids[0] == "b"
    assert set(ids) == {"a", "b", "c"}


def test_rrf_weights_and_limit():
    fused = rrf_fuse([["a"], ["b"]], k=60, weights=[3.0, 1.0], limit=1)
    assert len(fused) == 1
    assert fused[0][0] == "a"


def test_rrf_empty():
    assert rrf_fuse([[], []]) == []
