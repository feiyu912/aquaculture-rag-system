from __future__ import annotations

from types import SimpleNamespace

from app.retrieval import bm25, index_manifest


def test_bm25_config_hash_is_stable_across_calls():
    assert bm25.bm25_config_hash() == bm25.bm25_config_hash()


def test_bm25_config_hash_changes_with_tokenizer_config(monkeypatch):
    original = bm25.bm25_config_hash()
    monkeypatch.setattr(bm25, "CUSTOM_TERMS", [*bm25.CUSTOM_TERMS, "新增术语"])
    assert bm25.bm25_config_hash() != original


def test_tokenizer_config_records_its_inputs():
    config = bm25.tokenizer_config()
    assert config["implementation"] == "jieba+custom_terms"
    assert config["index_fn"] == "crc32&0x7fffffff"
    assert "溶解氧" in config["custom_terms"]
    assert config["jieba_version"]


def _manifest(**overrides):
    values = {
        "collection": "kb",
        "embedding_model": "BAAI/bge-m3",
        "vector_size": 1024,
        "chunk_config_hash": "chunk",
        "bm25_config_hash": "bm25",
        "status": "active",
        "document_count": 1,
        "point_count": 10,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_check_manifest_flags_bm25_mismatch(monkeypatch):
    async def fake_manifest(db, collection):
        return _manifest()

    monkeypatch.setattr(index_manifest, "get_manifest", fake_manifest)
    result = await index_manifest.check_manifest(
        None,
        collection="kb",
        embedding_model="BAAI/bge-m3",
        vector_size=1024,
        chunk_config_hash="chunk",
        bm25_config_hash="different",
    )
    assert result["ok"] is False
    assert "manifest_bm25_config_mismatch" in result["warnings"]
    assert result["bm25_config_hash"] == "bm25"


async def test_check_manifest_accepts_matching_bm25_hash(monkeypatch):
    async def fake_manifest(db, collection):
        return _manifest()

    monkeypatch.setattr(index_manifest, "get_manifest", fake_manifest)
    result = await index_manifest.check_manifest(
        None,
        collection="kb",
        embedding_model="BAAI/bge-m3",
        vector_size=1024,
        chunk_config_hash="chunk",
        bm25_config_hash="bm25",
    )
    assert result["ok"] is True
    assert result["warnings"] == []


async def test_check_manifest_without_expected_hash_does_not_warn(monkeypatch):
    async def fake_manifest(db, collection):
        return _manifest(bm25_config_hash="")

    monkeypatch.setattr(index_manifest, "get_manifest", fake_manifest)
    result = await index_manifest.check_manifest(
        None,
        collection="kb",
        embedding_model="BAAI/bge-m3",
        vector_size=1024,
    )
    assert result["ok"] is True
