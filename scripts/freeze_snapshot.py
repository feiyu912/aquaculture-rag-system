#!/usr/bin/env python3
"""Freeze the active corpus into an immutable, re-verifiable snapshot.

Why this exists
---------------
"1548 documents" is only a checkable thesis claim if the exact set, its
per-document licence basis and its index state are pinned at one instant.  This
script takes that photograph and gives it a hash:

  snapshots/<id>/snapshot.json        manifest: counts, gate status, config
  snapshots/<id>/documents.jsonl.gz   one record per active document
  snapshots/<id>/chunks.jsonl.gz      chunk text + hashes (local-only, gitignored)
  snapshots/<id>/SHA256SUMS           integrity of the artifacts above

Every document gets a digest over its frozen fields; the corpus digest is the
hash of the sorted (document_id, document_digest) list.  Re-running against an
unchanged database reproduces the corpus digest exactly -- that is the property
that makes the snapshot citable in a thesis.

Nothing here mutates Postgres, Qdrant or the document files.  The snapshot is
written read-only and an existing snapshot directory is never overwritten.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import gzip
import hashlib
import io
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

DOCUMENTS_SQL = """
SELECT
    d.id, d.title, d.category, d.species, d.source_org, d.source_url,
    d.publish_year, d.source_type, d.authority_level, d.fetched_at,
    d.effective_date, d.growth_stages, d.region, d.verification_status,
    d.technical_review_status, d.domain_review_status, d.review_flags,
    d.reviewed_at, d.source_trust, d.index_eligibility, d.risk_level,
    d.licence_class, d.licence_evidence, d.licence_review_id, d.doc_genre,
    d.created_at, d.updated_at, d.metadata,
    v.id AS version_id, v.version_no, v.content_hash, v.file_path,
    v.file_size, v.page_count, v.status AS version_status, v.parser_name,
    v.parser_version, v.embedding_model, v.chunk_config_hash, v.activated_at,
    r.scope AS review_scope, r.basis AS review_basis,
    r.decision AS review_decision, r.evidence_url, r.evidence_quote,
    r.reviewer, r.decided_at, r.evidence_kind, r.conditions
FROM kb_documents d
LEFT JOIN kb_document_versions v ON v.id = d.current_version_id
LEFT JOIN licence_reviews r ON r.id = d.licence_review_id
WHERE d.status = 'active'
ORDER BY d.id
"""

CHUNKS_SQL = """
SELECT ch.document_version_id, ch.id, ch.chunk_role, ch.ordinal, ch.content,
       ch.content_hash, ch.token_count, ch.page_from, ch.page_to,
       ch.heading_path, ch.parent_id
FROM kb_chunks ch
JOIN kb_documents d
  ON d.current_version_id = ch.document_version_id AND d.status = 'active'
ORDER BY d.id, ch.ordinal
"""

STATUS_SQL = """
SELECT d.status, count(DISTINCT d.id) AS documents,
       count(DISTINCT v.id) AS versions,
       count(ch.id) AS chunks
FROM kb_documents d
LEFT JOIN kb_document_versions v ON v.id = d.current_version_id
LEFT JOIN kb_chunks ch ON ch.document_version_id = v.id
GROUP BY 1 ORDER BY 1
"""

# Mirrors promote_eligible.GATE.  Kept as text so the manifest states the rule
# the corpus is judged against, rather than only its consequences.
PUBLISH_GATE = (
    "status='active' AND index_eligibility='eligible' "
    "AND technical_review_status<>'fail' AND source_trust IS NOT NULL "
    "AND source_trust<>'unknown' AND licence_review_id IS NOT NULL "
    "AND EXISTS (SELECT 1 FROM licence_reviews r "
    "WHERE r.id=kb_documents.licence_review_id AND r.decision='approved')"
)


def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return str(value)


@contextlib.contextmanager
def gzip_text_writer(path: Path):
    """Deterministic (mtime=0) gzip writer with a proper text-layer close order."""
    raw = open(path, "wb")  # noqa: SIM115 - closed in the finally below
    gz = gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0)
    text = io.TextIOWrapper(gz, encoding="utf-8")
    try:
        yield text
    finally:
        text.close()
        raw.close()


def canonical(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_default
    ).encode("utf-8")


def digest(payload: Any) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def source_group(record: dict) -> str:
    """The six groups the thesis reports, derived from publisher not guesses."""
    if record["source_org"] == "WorldFish":
        return "WorldFish"
    return {
        "official_standard": "standard",
        "official_local": "local",
        "official_national": "national",
        "research_institute": "journal",
    }.get(record["source_trust"] or "", "other")


def sha256_file(path: str | None, block: int = 1 << 20) -> str | None:
    if not path:
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(block), b""):
                h.update(chunk)
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None
    return h.hexdigest()


async def collect_documents(db) -> list[dict]:
    from sqlalchemy import text

    result = await db.stream(text(DOCUMENTS_SQL))
    rows = []
    async for row in result:
        rows.append(dict(row._mapping))
    return rows


async def collect_chunks(db, out_path: Path) -> tuple[dict[str, dict], dict]:
    """Stream chunks to gzip, returning per-version aggregates and integrity stats."""
    from sqlalchemy import text

    stats: dict[str, dict] = defaultdict(
        lambda: {"chunks": 0, "child_chunks": 0, "tokens": 0, "hasher": hashlib.sha256()}
    )
    mismatched = 0
    missing_text = 0
    total = 0
    result = await db.stream(text(CHUNKS_SQL))
    with gzip_text_writer(out_path) as fh:
        async for row in result:
            r = dict(row._mapping)
            vid = str(r["document_version_id"])
            st = stats[vid]
            st["chunks"] += 1
            if r["chunk_role"] == "child":
                st["child_chunks"] += 1
            st["tokens"] += r["token_count"] or 0
            st["hasher"].update(f"{r['ordinal']}\t{r['content_hash']}\n".encode())

            content = r["content"] or ""
            if not content:
                missing_text += 1
            if hashlib.sha256(content.encode("utf-8")).hexdigest() != r["content_hash"]:
                mismatched += 1

            fh.write(
                json.dumps(
                    {
                        "chunk_id": str(r["id"]),
                        "document_version_id": vid,
                        "parent_id": str(r["parent_id"]) if r["parent_id"] else None,
                        "chunk_role": r["chunk_role"],
                        "ordinal": r["ordinal"],
                        "content": content,
                        "content_hash": r["content_hash"],
                        "token_count": r["token_count"],
                        "page_from": r["page_from"],
                        "page_to": r["page_to"],
                        "heading_path": r["heading_path"] or [],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            total += 1
            if total % 50000 == 0:
                print(f"  chunks {total} ...", file=sys.stderr)

    for st in stats.values():
        st["digest"] = st.pop("hasher").hexdigest()
    integrity = {"chunks_written": total, "hash_mismatch": mismatched, "empty_content": missing_text}
    return dict(stats), integrity


def qdrant_index(collection: str, url: str) -> dict[str, int]:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=url)
    counts: Counter = Counter()
    offset = None
    while True:
        points, offset = client.scroll(
            collection,
            limit=8192,
            offset=offset,
            with_payload=["document_version_id"],
            with_vectors=False,
        )
        for point in points:
            counts[str(point.payload.get("document_version_id"))] += 1
        if offset is None:
            break
    info = client.get_collection(collection)
    return {
        "points": counts,
        "collection_points": info.points_count or 0,
        "vector_size": info.config.params.vectors.size,
        "distance": str(info.config.params.vectors.distance),
    }


def git_state() -> dict:
    import subprocess

    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
        ).stdout.strip()

    return {
        "commit": run("rev-parse", "HEAD") or None,
        "branch": run("rev-parse", "--abbrev-ref", "HEAD") or None,
        "dirty": bool(run("status", "--porcelain")),
    }


def gate_reasons(record: dict) -> list[str]:
    reasons = []
    if record["index_eligibility"] != "eligible":
        reasons.append(f"index_eligibility={record['index_eligibility']}")
    if record["technical_review_status"] == "fail":
        reasons.append("technical_review=fail")
    if not record["source_trust"] or record["source_trust"] == "unknown":
        reasons.append(f"source_trust={record['source_trust']}")
    review = record["licence_review"]
    if not review["id"]:
        reasons.append("no_licence_review_id")
    elif review["decision"] != "approved":
        reasons.append(f"licence_review={review['decision']}")
    return reasons


async def build(args: argparse.Namespace) -> int:
    from sqlalchemy import text

    from app.config import settings
    from app.db import SessionLocal

    frozen_at = datetime.now(UTC)
    snapshot_id = args.snapshot_id or f"kb-v1_{frozen_at:%Y%m%d}"
    out_dir = ROOT / "snapshots" / snapshot_id
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"refusing to overwrite existing snapshot: {out_dir}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    docs_path = out_dir / "documents.jsonl.gz"
    chunks_path = out_dir / "chunks.jsonl.gz"

    async with SessionLocal() as db:
        # A freeze must see one instant, not a moving target.
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        server_version = (await db.execute(text("SHOW server_version"))).scalar_one()
        docs = await collect_documents(db)
        print(f"documents: {len(docs)}", file=sys.stderr)
        chunk_stats, chunk_integrity = await collect_chunks(db, chunks_path)
        statuses = [
            dict(r._mapping) for r in (await db.execute(text(STATUS_SQL))).all()
        ]
        index_manifests = [
            dict(r._mapping)
            for r in (
                await db.execute(
                    text(
                        "SELECT collection, embedding_model, vector_size, chunk_config_hash, "
                        "bm25_config_hash, status, document_count, point_count, updated_at "
                        "FROM index_manifests ORDER BY collection"
                    )
                )
            ).all()
        ]

    # Document bytes: hash the source files in parallel; a missing file is a
    # fact worth recording, not a reason to abort the freeze.
    def file_state(item: dict) -> tuple[str, str | None]:
        return str(item["id"]), sha256_file(item["file_path"])

    print("hashing source files ...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=16) as pool:
        file_hashes = dict(pool.map(file_state, docs))

    print("scrolling qdrant ...", file=sys.stderr)
    qdrant = await asyncio.to_thread(
        qdrant_index, settings.qdrant_collection, settings.qdrant_url
    )
    point_counts: Counter = qdrant["points"]

    records: list[dict] = []
    for row in docs:
        vid = str(row["version_id"]) if row["version_id"] else None
        ch = chunk_stats.get(vid, {}) if vid else {}
        review = {
            "id": str(row["licence_review_id"]) if row["licence_review_id"] else None,
            "scope": row["review_scope"],
            "basis": row["review_basis"],
            "decision": row["review_decision"],
            "evidence_url": row["evidence_url"],
            "evidence_quote": row["evidence_quote"],
            "reviewer": row["reviewer"],
            "decided_at": row["decided_at"],
            "evidence_kind": row["evidence_kind"],
            "conditions": row["conditions"],
        }
        record = {
            "document_id": str(row["id"]),
            "title": row["title"],
            "category": row["category"],
            "species": row["species"] or [],
            "source_org": row["source_org"],
            "source_url": row["source_url"],
            "publish_year": row["publish_year"],
            "source_type": row["source_type"],
            "authority_level": row["authority_level"],
            "region": row["region"],
            "doc_genre": row["doc_genre"],
            "growth_stages": row["growth_stages"] or [],
            "effective_date": row["effective_date"],
            "fetched_at": row["fetched_at"],
            "verification_status": row["verification_status"],
            "metadata": row["metadata"] or {},
            "trust": {
                "source_trust": row["source_trust"],
                "authority_level": row["authority_level"],
                "risk_level": row["risk_level"],
            },
            "licence": {
                "class": row["licence_class"],
                "index_eligibility": row["index_eligibility"],
                "evidence": row["licence_evidence"],
                "review_id": review["id"],
                "review": review,
            },
            "review": {
                "technical": row["technical_review_status"],
                "technical_flags": row["review_flags"] or [],
                "reviewed_at": row["reviewed_at"],
                "domain": row["domain_review_status"],
            },
            "version": {
                "id": vid,
                "version_no": row["version_no"],
                "content_hash": row["content_hash"],
                "status": row["version_status"],
                "file_path": row["file_path"],
                "file_size": row["file_size"],
                "page_count": row["page_count"],
                "parser_name": row["parser_name"],
                "parser_version": row["parser_version"],
                "embedding_model": row["embedding_model"],
                "chunk_config_hash": row["chunk_config_hash"],
                "activated_at": row["activated_at"],
            },
            "file": {
                "sha256": file_hashes.get(str(row["id"])),
                "exists": file_hashes.get(str(row["id"])) is not None,
            },
            "chunks": {
                "count": ch.get("chunks", 0),
                "child_count": ch.get("child_chunks", 0),
                "token_count": ch.get("tokens", 0),
                "digest": ch.get("digest"),
            },
            "index": {
                "collection": settings.qdrant_collection,
                "points": int(point_counts.get(vid, 0)) if vid else 0,
            },
        }
        record["source_group"] = source_group(record)
        # The digest covers the frozen facts only; the gate verdict is derived
        # and therefore kept outside it, so a rule change does not rewrite the
        # corpus fingerprint.
        record["document_digest"] = digest(record)
        reasons = gate_reasons(record)
        record["gate"] = {"publishable_now": not reasons, "reasons": reasons}
        records.append(record)

    # Keep the per-document digests inside the artifact as well, so a reader can
    # verify a single document without recomputing the whole corpus.
    records.sort(key=lambda r: r["document_id"])
    corpus_digest = digest([f"{r['document_id']}:{r['document_digest']}" for r in records])

    with gzip_text_writer(docs_path) as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    # ---- manifest ---------------------------------------------------------
    def key(value) -> str:
        return "(none)" if value is None else str(value)

    def tally(fn) -> dict:
        return dict(
            sorted(
                Counter(key(fn(r)) for r in records).items(), key=lambda kv: (-kv[1], kv[0])
            )
        )

    review_rows = {
        str(r["id"]): {
            "scope": r["scope"],
            "basis": r["basis"],
            "decision": r["decision"],
            "evidence_kind": r["evidence_kind"],
            "conditions": r["conditions"],
            "evidence_url": r["evidence_url"],
            "evidence_quote": r["evidence_quote"],
            "reviewer": r["reviewer"],
            "decided_at": r["decided_at"],
        }
        for r in (
            [rec["licence"]["review"] for rec in records if rec["licence"]["review"]["id"]]
        )
    }

    blocked = [r for r in records if not r["gate"]["publishable_now"]]
    blocked_by_reason = Counter(reason for r in blocked for reason in r["gate"]["reasons"])

    missing_version = [r for r in records if not r["version"]["id"]]
    not_ready = [r for r in records if r["version"]["status"] != "ready" and r["version"]["id"]]
    missing_file = [r for r in records if not r["file"]["exists"]]
    no_points = [
        r for r in records if r["chunks"]["child_count"] and not r["index"]["points"]
    ]
    partial_points = [
        r
        for r in records
        if r["chunks"]["child_count"]
        and 0 < r["index"]["points"] < r["chunks"]["child_count"]
    ]
    dup_groups: dict[str, list[str]] = defaultdict(list)
    for r in records:
        if r["version"]["content_hash"]:
            dup_groups[r["version"]["content_hash"]].append(r["document_id"])
    duplicates = {k: v for k, v in dup_groups.items() if len(v) > 1}

    total_chunks = sum(r["chunks"]["count"] for r in records)
    total_child = sum(r["chunks"]["child_count"] for r in records)
    total_tokens = sum(r["chunks"]["token_count"] for r in records)
    active_versions = {r["version"]["id"] for r in records if r["version"]["id"]}
    stale_points = sum(n for vid, n in point_counts.items() if vid not in active_versions)

    caveats = [
        (
            f"domain_review_status 的取值分布为 {tally(lambda r: r['review']['domain'])}；"
            "本快照不声称任何专家审核已发生。"
        ),
        (
            f"{len(blocked)} 篇 active 文档不满足现行发布门禁（"
            f"{dict(blocked_by_reason)}）；它们是历史批次，按原状冻结，未做任何改写。"
        ),
        (
            f"{len(missing_version)} 篇 active 文档没有 current_version，"
            f"{len(not_ready)} 篇当前版本状态不是 ready。"
        ),
        f"{len(missing_file)} 篇源文件在磁盘上缺失，file.sha256 记为 null。",
        (
            f"{len(no_points)} 篇有子块但 Qdrant 无向量，"
            f"{len(partial_points)} 篇向量数少于子块数。"
        ),
    ]
    if duplicates:
        caveats.append(
            f"content_hash 重复 {len(duplicates)} 组，"
            f"涉及 {sum(len(v) for v in duplicates.values())} 篇（重印/转载）；"
            "快照按原状保留，未合并计数。"
        )
    if chunk_integrity["hash_mismatch"]:
        caveats.append(f"{chunk_integrity['hash_mismatch']} 个块的 content_hash 与正文重算不一致。")

    manifest = {
        "snapshot_id": snapshot_id,
        "label": args.label,
        "frozen_at": frozen_at.isoformat().replace("+00:00", "Z"),
        "frozen_at_local": frozen_at.astimezone().isoformat(),
        "corpus_digest": corpus_digest,
        "document_count": len(records),
        "documents": {
            "by_source_group": tally(lambda r: r["source_group"]),
            "by_source_trust": tally(lambda r: r["trust"]["source_trust"]),
            "by_licence_class": tally(lambda r: r["licence"]["class"]),
            "by_index_eligibility": tally(lambda r: r["licence"]["index_eligibility"]),
            "by_technical_review": tally(lambda r: r["review"]["technical"]),
            "by_domain_review": tally(lambda r: r["review"]["domain"]),
            "by_risk_level": tally(lambda r: r["trust"]["risk_level"]),
            "by_doc_genre": tally(lambda r: r["doc_genre"]),
            "by_source_type": tally(lambda r: r["source_type"]),
            "by_category": tally(lambda r: r["category"]),
            "by_language": tally(lambda r: r["metadata"].get("language")),
            "by_region": tally(lambda r: r["region"]),
            "top_source_orgs": tally(lambda r: r["source_org"]),
            "isolated_for_licence": tally(
                lambda r: (r["metadata"].get("licence_isolation") or {}).get("reason")
                or "(not isolated)"
            ),
        },
        "chunks": {
            "chunks": total_chunks,
            "child_chunks": total_child,
            "parent_chunks": total_chunks - total_child,
            "tokens": total_tokens,
            "mean_chunks_per_document": round(total_chunks / max(len(records), 1), 2),
            "integrity": chunk_integrity,
        },
        "index": {
            "collection": settings.qdrant_collection,
            "vector_size": qdrant["vector_size"],
            "distance": qdrant["distance"],
            "points": qdrant["collection_points"],
            "active_version_points": qdrant["collection_points"] - stale_points,
            "stale_points": stale_points,
            "documents_without_points": len(no_points),
            "documents_partial_points": len(partial_points),
            "index_manifests": index_manifests,
        },
        "publish_gate": {
            "rule": PUBLISH_GATE,
            "publishable_now": len(records) - len(blocked),
            "blocked": len(blocked),
            "blocked_by_reason": dict(blocked_by_reason),
            "note": "门禁只用于说明可发布性；快照包含 active 集合的全部文档，未按门禁筛除。",
        },
        "licence_reviews": review_rows,
        "config": {
            "embedding_model": settings.embedding_model,
            "embedding_device": settings.embedding_device,
            "embedding_use_fp16": settings.embedding_use_fp16,
            "embedding_batch_size": settings.embedding_batch_size,
            "embedding_max_length": settings.embedding_max_length,
            "reranker_model": settings.reranker_model,
            "reranker_device": settings.reranker_device,
            "retrieval": {
                "default_mode": settings.default_retrieval_mode,
                "dense_top_k": settings.dense_top_k,
                "bm25_top_k": settings.bm25_top_k,
                "rrf_k": settings.rrf_k,
                "rerank_top_k": settings.rerank_top_k,
                "max_sources": settings.max_sources,
            },
            "llm": {
                "provider": settings.llm_provider,
                "model": settings.openai_model or settings.deepseek_model,
            },
        },
        "state_outside_snapshot": statuses,
        "server_version": server_version,
        "git": git_state(),
        "caveats": caveats,
        "artifacts": {},
    }

    def add_artifact(name: str, path: Path) -> dict:
        data = path.read_bytes()
        info = {
            "file": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
        manifest["artifacts"][name] = info
        return info

    add_artifact("documents.jsonl.gz", docs_path)
    add_artifact("chunks.jsonl.gz", chunks_path)

    snapshot_path = out_dir / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_default) + "\n",
        encoding="utf-8",
    )

    sums = [f"{info['sha256']}  {name}" for name, info in manifest["artifacts"].items()]
    (out_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")

    # Immutable on disk: read-only files, no new entries in the directory.
    for path in (docs_path, chunks_path, snapshot_path, out_dir / "SHA256SUMS"):
        path.chmod(0o444)
    out_dir.chmod(0o555)

    print(f"snapshot {snapshot_id}: {len(records)} documents, digest {corpus_digest}")
    print(f"chunks {total_chunks} ({total_child} child), tokens {total_tokens}")
    print(f"gate: {len(records) - len(blocked)} publishable / {len(blocked)} blocked")
    print(f"wrote {out_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot-id", default=None, help="default kb-v1_<UTC date>")
    parser.add_argument("--label", default="KB-v1")
    return asyncio.run(build(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())