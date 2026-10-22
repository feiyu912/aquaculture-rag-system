"""Pure helpers shared by the data-management query API.

The helpers here never touch the database.  They answer three questions that
must be answered identically everywhere:

* what counts as one *independent source* (not one database row);
* what kind of material a document is (formal standard, draft, guidance, ...);
* how a document list rolls up into the counters shown in the UI.

Keeping this logic out of the router makes the definitions testable without a
live PostgreSQL/Qdrant, which matters because a wrong total is a data-quality
claim, not a cosmetic bug.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urlsplit, urlunsplit

BINDING_AUTHORITIES = frozenset({"national_standard", "industry_standard", "local_standard"})
RESEARCH_AUTHORITIES = frozenset({"peer_reviewed", "international"})

DOCUMENT_TYPE_LABELS: dict[str, str] = {
    "standard": "正式标准",
    "standard_draft": "征求意见稿",
    "technical_guidance": "技术指导",
    "research": "论文/科研资料",
    "synthetic": "合成示例",
    "other": "其他/未分类",
}

# Filtering by document type is an authority-group filter, so the mapping is
# kept next to the label map instead of being duplicated in SQL.
DOCUMENT_TYPE_AUTHORITIES: dict[str, frozenset[str]] = {
    "standard": BINDING_AUTHORITIES,
    "standard_draft": frozenset({"standard_draft"}),
    "technical_guidance": frozenset({"official_technical", "local_guidance"}),
    "research": RESEARCH_AUTHORITIES,
    "synthetic": frozenset({"synthetic"}),
}


def normalize_source_url(value: str | None) -> str | None:
    """Normalise a URL enough to recognise the same source twice.

    Deliberately conservative: only scheme/host case, default ports, fragments
    and a trailing slash are normalised.  Query strings stay intact because
    they often identify the actual document (``?id=123``).
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.lower()
    host = (parts.hostname or "").lower()
    host = host.removeprefix("www.")
    port = parts.port
    netloc = host
    if port and port not in {80, 443}:
        netloc = f"{host}:{port}"
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", netloc, path, parts.query, ""))


def source_identity(
    *,
    source_url: str | None,
    content_hash: str | None,
    document_id: str,
) -> str:
    """Return the key used to count independent source material.

    Priority: canonical URL, then the current version's content hash, then the
    document id.  A new *version* of the same document keeps the same URL/hash
    slot; a duplicate upload with the same bytes collapses onto the hash; a
    test row with no provenance still counts once instead of disappearing.
    """
    url = normalize_source_url(source_url)
    if url:
        return f"url:{url}"
    if content_hash:
        return f"sha256:{content_hash}"
    return f"document:{document_id}"


def classify_document_type(authority_level: str | None, metadata: dict | None = None) -> str:
    """Map authority + collector metadata to a UI-level material type.

    The authority level remains the source of truth for trust; ``doc_type`` is
    only a display/filter grouping.  A draft marker wins over a mislabelled
    binding authority because that mistake is exactly what the staging review
    found (DB46).
    """
    meta = metadata or {}
    authority = (authority_level or "unknown").strip().lower()
    declared = str(meta.get("doc_type") or "").strip().lower()
    doc_status = str(meta.get("document_status") or "").strip().lower()

    if authority == "standard_draft" or doc_status == "draft" or declared == "standard_draft":
        return "standard_draft"
    if authority == "synthetic":
        return "synthetic"
    if authority in BINDING_AUTHORITIES:
        return "standard"
    if authority in {"official_technical", "local_guidance"}:
        return "technical_guidance"
    if authority in RESEARCH_AUTHORITIES or declared in {"research", "paper", "journal"}:
        return "research"
    return "other"


def document_type_label(value: str) -> str:
    return DOCUMENT_TYPE_LABELS.get(value, DOCUMENT_TYPE_LABELS["other"])


def is_failed_document(row: dict) -> bool:
    """Return True when a live document has no usable version and its latest
    ingestion attempt failed.

    ``kb_documents.status`` stays ``staging`` while a collector retries; the
    failure lives on the version/job.  The management UI still needs a single
    "failed" bucket, and it must not also count that row as merely "staging".
    """
    if row.get("status") == "deleted":
        return False
    if row.get("status") == "failed":
        return True
    return (
        row.get("current_version_id") is None
        and row.get("latest_version_status") == "failed"
    )


def summarize_documents(rows: list[dict]) -> dict:
    """Roll document rows up into the counters the management UI displays.

    ``rows`` are lightweight dicts with ``id``, ``status``,
    ``verification_status``, ``current_version_id``, ``source_url``,
    ``content_hash`` and ``document_type``.  ``deleted`` rows are included so
    the caller can report them, but they never enter an effective count.
    """
    by_status: Counter[str] = Counter()
    by_status_including_deleted: Counter[str] = Counter()
    by_verification: Counter[str] = Counter()
    by_document_type: Counter[str] = Counter()
    by_review: dict[str, Counter[str]] = {
        "technical": Counter(),
        "domain": Counter(),
    }

    non_deleted = [row for row in rows if row.get("status") != "deleted"]
    failed = [row for row in non_deleted if is_failed_document(row)]
    active = [
        row
        for row in non_deleted
        if row.get("status") == "active" and not is_failed_document(row)
    ]
    staging = [
        row
        for row in non_deleted
        if row.get("status") == "staging" and not is_failed_document(row)
    ]
    deleted = [row for row in rows if row.get("status") == "deleted"]

    for row in rows:
        display_status = "failed" if is_failed_document(row) else row.get("status")
        by_status_including_deleted[str(display_status or "unknown")] += 1
        if row.get("status") != "deleted":
            by_status[str(display_status or "unknown")] += 1
    # Deleted test records must not leak into the trust/type distributions or
    # the non-deleted status bucket; ``by_status_including_deleted`` reports
    # them separately.
    for row in non_deleted:
        by_verification[str(row.get("verification_status") or "unknown")] += 1
        by_document_type[str(row.get("document_type") or "other")] += 1
        by_review["technical"][str(row.get("technical_review_status") or "pending")] += 1
        by_review["domain"][str(row.get("domain_review_status") or "pending")] += 1

    def distinct(rows_subset: list[dict]) -> int:
        return len(
            {
                row.get("source_key")
                or source_identity(
                    source_url=row.get("source_url"),
                    content_hash=row.get("content_hash"),
                    document_id=str(row.get("id")),
                )
                for row in rows_subset
            }
        )

    effective = [
        row
        for row in active
        if row.get("current_version_id") is not None
        and str(row.get("verification_status") or "") == "verified"
    ]
    retrievable = [row for row in effective if row.get("current_version_status") == "ready"]
    all_non_deleted_sources = distinct(non_deleted)
    return {
        "total": len(non_deleted),
        "records_including_deleted": len(rows),
        "by_status": dict(sorted(by_status.items())),
        "by_status_including_deleted": dict(sorted(by_status_including_deleted.items())),
        "by_verification": dict(sorted(by_verification.items())),
        "by_document_type": dict(sorted(by_document_type.items())),
        "by_review_status": {
            "technical": dict(sorted(by_review["technical"].items())),
            "domain": dict(sorted(by_review["domain"].items())),
        },
        "active": len(active),
        "staging": len(staging),
        "failed": len(failed),
        "deleted": len(deleted),
        "published": len(effective),
        # Published is a trust/visibility statement; retrievable additionally
        # requires the current version to be indexed and ready.
        "retrievable": len(retrievable),
        "with_current_version": sum(
            1 for row in non_deleted if row.get("current_version_id") is not None
        ),
        "independent_sources": {
            "total": all_non_deleted_sources,
            "active": distinct(active),
            "staging": distinct(staging),
            "effective": distinct(effective),
            # A staging row may point at a current version; it is still not
            # published.  Keep that explicit instead of letting the presence of
            # current_version_id imply publication.
            "staging_with_current_version": sum(
                1 for row in staging if row.get("current_version_id") is not None
            ),
            "duplicate_or_repeated_records": max(0, len(non_deleted) - all_non_deleted_sources),
        },
    }


def summarize_versions(rows: list[dict]) -> dict:
    """Count versions by lifecycle status and multi-version documents."""
    by_status: Counter[str] = Counter(str(row.get("status") or "unknown") for row in rows)
    docs: dict[str, int] = defaultdict(int)
    for row in rows:
        docs[str(row.get("document_id"))] += 1
    return {
        "total": len(rows),
        "by_status": dict(sorted(by_status.items())),
        "documents_with_multiple_versions": sum(1 for count in docs.values() if count > 1),
    }


def summarize_chunks(rows: list[dict]) -> dict:
    """Count parent/child chunks for a set of versions.

    ``rows`` carry ``chunk_role`` and ``count``.  Only the current active
    versions should be passed for the "active" bucket; this helper does not
    guess what "active" means.
    """
    by_role: Counter[str] = Counter()
    for row in rows:
        by_role[str(row.get("chunk_role") or "unknown")] += int(row.get("count") or 0)
    return {
        "parent": by_role.get("parent", 0),
        "child": by_role.get("child", 0),
        "total": by_role.get("parent", 0) + by_role.get("child", 0),
    }


REVIEW_FLAG_LABELS: dict[str, str] = {
    "chunk_over_3000_chars": "存在超长块（>3000 字符），可能混入多段内容",
    "chunk_under_40_chars": "存在过短块（<40 字符），可能是页眉页脚或残句",
    "chunk_without_page": "存在缺少页码定位的块",
    "cross_page_chunk": "跨页块：引用时需回到父块核对完整语义",
    "duplicate_chunk_text": "重复块：页眉/页脚或重复段落",
    "has_markdown_tables": "包含表格；表格转 Markdown 后结构可能失真",
    "heading_pollution": "标题层级可能被正文污染",
    "mostly_missing_section_path": "多数块缺少章节路径，引用上下文可能不完整",
    "navigation_boilerplate": "导航/页眉页脚模板文本混入正文",
    "low_chunk_density": "每页块密度过低，可能只解析出页面框架",
    "no_chunks": "未解析出任何块（可能是扫描件或无文本层）",
    "no_text_layer_scanned_pdf": "PDF 无文本层，需要 OCR 才能使用",
    "scanned_no_text_layer": "PDF 无文本层，需要 OCR 才能使用",
    "possibly_attachment_only": "正文可能在附件中，当前页面只有通知/函件",
    "content_in_attachment_only": "正文在附件中，当前页面只有通知/函件",
    "draft_body_in_attachment_only": "标准正文在附件中，当前页面只有征求意见函",
}


def describe_review_flag(code: str) -> str:
    """Human-readable explanation for a machine quality flag.

    Some flags carry a count or percentage (``duplicate_chunk_text x2``,
    ``word_split_46pct``).  Parse those known suffixes so the UI does not show
    a raw machine token; unknown flags still pass through verbatim.
    """
    if code in REVIEW_FLAG_LABELS:
        return REVIEW_FLAG_LABELS[code]
    if code.startswith("word_split_") and code.endswith("pct"):
        return f"{code.removeprefix('word_split_').removesuffix('pct')}% 的块以残词开头，英文断句可能失败"
    if code.startswith("cross_page_dominant x") and code.endswith("%"):
        return f"跨页块占 {code.removeprefix('cross_page_dominant x')}，引用时需核对完整上下文"
    if code.startswith("duplicate_chunk_text x"):
        return f"重复块 {code.removeprefix('duplicate_chunk_text x')} 处：页眉/页脚或重复段落"
    if code.startswith("table_heavy x"):
        return f"表格块 {code.removeprefix('table_heavy x')} 个，表格转 Markdown 后结构可能失真"
    if code.startswith("heading_pollution x"):
        return f"{code.removeprefix('heading_pollution x')} 个块标题层级受正文污染"
    if code.startswith("mojibake:"):
        return f"疑似乱码：{code.removeprefix('mojibake:').strip()}"
    return code
