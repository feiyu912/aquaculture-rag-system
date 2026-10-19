from __future__ import annotations

from app.retrieval.bm25 import BM25SparseEncoder, tokenize


def test_domain_terms_survive_tokenization():
    tokens = tokenize("中华绒螯蟹养殖水体的溶解氧应保持在 5 mg/L 以上")
    assert "中华绒螯蟹" in tokens
    assert "溶解氧" in tokens
    assert "5" in tokens
    assert "mg" in tokens


def test_document_and_query_vectors():
    encoder = BM25SparseEncoder(k1=1.2, b=0.75, avg_len=100)
    doc = encoder.document_vector("凡纳滨对虾养殖需要关注盐度和氨氮。")
    query = encoder.query_vector("对虾 盐度")
    assert doc.indices
    assert query.indices
    assert len(doc.indices) == len(doc.values)
    assert all(value > 0 for value in doc.values)


def test_empty_text():
    encoder = BM25SparseEncoder()
    assert encoder.document_vector("").indices == []
    assert encoder.query_vector("").indices == []
