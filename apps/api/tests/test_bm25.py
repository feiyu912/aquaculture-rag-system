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


def test_query_vector_has_unit_weights_and_unique_indices():
    encoder = BM25SparseEncoder(k1=1.2, b=0.75, avg_len=100)
    vector = encoder.query_vector("对虾 对虾 盐度")
    assert len(vector.indices) == len(set(vector.indices))
    assert all(value == 1.0 for value in vector.values)


def test_document_vector_does_not_apply_idf():
    encoder = BM25SparseEncoder(k1=1.2, b=0.75, avg_len=100)
    single = encoder.document_vector("溶解氧")
    repeated = encoder.document_vector("溶解氧 溶解氧")
    assert len(single.indices) == 1
    assert repeated.values[0] > single.values[0]


def test_best_sentence_handles_dissolved_oxygen_alias():
    from app.retrieval.service import best_sentence

    text = (
        "8.1水质指标溶氧量5mg/L以上，pH值7.5~8.5，透明度30cm~50cm。 "
        "8.2水质调控按照“前期肥，中后期瘦，弱碱性”的原则调控水质。"
    )
    quote = best_sentence(text, "中华绒螯蟹对溶解氧有什么要求？")
    assert "5mg/L" in quote
