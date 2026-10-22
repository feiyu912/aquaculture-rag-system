from __future__ import annotations

from app.management.catalog import (
    classify_document_type,
    describe_review_flag,
    is_failed_document,
    normalize_source_url,
    source_identity,
    summarize_chunks,
    summarize_documents,
    summarize_versions,
)


def doc(**overrides):
    row = {
        "id": "doc-1",
        "status": "active",
        "verification_status": "verified",
        "current_version_id": "v1",
        "current_version_status": "ready",
        "source_url": "https://example.org/standard.pdf",
        "content_hash": "a" * 64,
        "document_type": "standard",
        "technical_review_status": "pass",
        "domain_review_status": "pending",
    }
    row.update(overrides)
    return row


def test_url_normalisation_removes_fragment_and_case():
    assert (
        normalize_source_url("HTTPS://WWW.Example.ORG/path/doc.pdf#page=2")
        == "https://example.org/path/doc.pdf"
    )
    assert normalize_source_url("http://example.org/path/doc.pdf/") == normalize_source_url(
        "https://example.org/path/doc.pdf"
    )


def test_same_url_or_hash_counts_as_one_independent_source():
    first = source_identity(
        source_url="https://example.org/a.pdf", content_hash="a", document_id="1"
    )
    second = source_identity(
        source_url="https://www.example.org/a.pdf#x", content_hash="b", document_id="2"
    )
    assert first == second

    no_url_first = source_identity(source_url=None, content_hash="same", document_id="1")
    no_url_second = source_identity(source_url=None, content_hash="same", document_id="2")
    assert no_url_first == no_url_second


def test_document_type_distinguishes_draft_from_binding_standard():
    assert classify_document_type("local_standard", {}) == "standard"
    assert classify_document_type("local_standard", {"document_status": "draft"}) == "standard_draft"
    assert classify_document_type("standard_draft", {}) == "standard_draft"
    assert classify_document_type("official_technical", {}) == "technical_guidance"
    assert classify_document_type("peer_reviewed", {}) == "research"
    assert classify_document_type("synthetic", {}) == "synthetic"


def test_staging_with_current_version_is_not_published_and_not_effective():
    rows = [
        doc(id="a", status="active", current_version_id="v1"),
        doc(id="b", status="staging", verification_status="pending", current_version_id="v2"),
        doc(id="c", status="deleted", verification_status="verified", current_version_id=None),
    ]
    stats = summarize_documents(rows)
    assert stats["total"] == 2
    assert stats["active"] == 1
    assert stats["staging"] == 1
    assert stats["independent_sources"]["staging_with_current_version"] == 1
    assert stats["published"] == 1
    assert stats["retrievable"] == 1
    assert stats["independent_sources"]["effective"] == 1
    assert stats["independent_sources"]["staging"] == 1
    # Deleted rows are reported, but never enter the verification/type mix.
    assert stats["deleted"] == 1
    assert "deleted" not in stats["by_status"]
    assert stats["by_status_including_deleted"]["deleted"] == 1
    assert stats["by_verification"] == {"pending": 1, "verified": 1}
    assert stats["by_document_type"] == {"standard": 2}


def test_failed_retry_without_current_version_is_failed_not_staging():
    row = doc(
        id="a",
        status="staging",
        verification_status="pending",
        current_version_id=None,
        current_version_status=None,
        latest_version_status="failed",
    )
    assert is_failed_document(row) is True
    stats = summarize_documents([row])
    assert stats["failed"] == 1
    assert stats["staging"] == 0
    assert stats["by_status"] == {"failed": 1}
    assert stats["total"] == 1


def test_failed_latest_version_does_not_hide_a_ready_current_version():
    row = doc(
        id="a",
        current_version_status="ready",
        latest_version_status="failed",
    )
    assert is_failed_document(row) is False
    stats = summarize_documents([row])
    assert stats["failed"] == 0
    assert stats["active"] == 1
    assert stats["retrievable"] == 1


def test_published_version_that_is_not_ready_is_not_retrievable():
    rows = [
        doc(id="a", current_version_status="processing"),
        doc(id="b", current_version_status="failed"),
        doc(id="c", current_version_status="ready"),
    ]
    stats = summarize_documents(rows)
    assert stats["published"] == 3
    assert stats["retrievable"] == 1


def test_duplicate_and_multiversion_rows_do_not_inflate_effective_sources():
    rows = [
        doc(id="a", source_url="https://example.org/x.pdf"),
        doc(id="b", source_url="http://www.example.org/x.pdf#top"),
        doc(id="c", source_url=None, content_hash="same"),
        doc(id="d", source_url=None, content_hash="same"),
    ]
    stats = summarize_documents(rows)
    assert stats["total"] == 4
    assert stats["independent_sources"]["total"] == 2
    assert stats["independent_sources"]["duplicate_or_repeated_records"] == 2

    versions = summarize_versions(
        [
            {"document_id": "a", "status": "ready"},
            {"document_id": "a", "status": "archived"},
            {"document_id": "b", "status": "failed"},
        ]
    )
    assert versions["total"] == 3
    assert versions["documents_with_multiple_versions"] == 1
    assert versions["by_status"] == {"archived": 1, "failed": 1, "ready": 1}


def test_chunks_are_counted_by_role():
    stats = summarize_chunks(
        [
            {"chunk_role": "parent", "count": 3},
            {"chunk_role": "child", "count": 9},
        ]
    )
    assert stats == {"parent": 3, "child": 9, "total": 12}


def test_unknown_review_flag_stays_verbatim():
    assert describe_review_flag("word_split_40pct").startswith("40% 的块")
    assert describe_review_flag("duplicate_chunk_text x2").startswith("重复块 2 处")
    assert describe_review_flag("table_heavy x6").startswith("表格块 6 个")
    assert describe_review_flag("mojibake:'Ã¤'") == "疑似乱码：'Ã¤'"
    assert describe_review_flag("custom_flag") == "custom_flag"
