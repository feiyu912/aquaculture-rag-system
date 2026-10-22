#!/usr/bin/env python3
"""Import ``data/inbox/<id>/`` into the knowledge base as **staging** documents.

Staging is enforced by ``KbDocument.status="staging"``: the pipeline still
parses, chunks and indexes the material, but retrieval only reads versions of
``status="active"`` documents, so nothing unpublished can be cited.

Every imported document is written with ``verification_status="pending"`` and
must be promoted deliberately (API or CLI) after a human check.

Usage:
    uv run python ../../scripts/ingest_inbox.py --dry-run
    uv run python ../../scripts/ingest_inbox.py --only wf-pond-aeration
    uv run python ../../scripts/ingest_inbox.py --report ../../data/reports/batch1_ingest.json
"""

from __future__ import annotations

import argparse
import hashlib
import asyncio
import json
import re
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.ingestion.pipeline import ingest_version  # noqa: E402
from app.models import KbChunk, KbDocument, KbDocumentVersion, KbIngestJob  # noqa: E402
from app.species import parse_species  # noqa: E402


def _year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def _load_meta(directory: Path) -> dict | None:
    path = directory / "meta.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


async def _existing_version(db, sha: str) -> KbDocumentVersion | None:
    return (
        await db.execute(
            select(KbDocumentVersion).where(
                KbDocumentVersion.content_hash == sha,
                KbDocumentVersion.status.in_(["processing", "ready"]),
            )
        )
    ).scalars().first()


async def ingest_one(
    directory: Path, meta: dict, *, dry_run: bool, force: bool = False
) -> dict:
    source_id = directory.name
    result: dict = {"id": source_id, "status": "pending"}
    original = next(
        (p for p in directory.iterdir() if p.name.startswith("original.")), None
    )
    if original is None:
        result.update(status="skipped", reason="no original file")
        return result

    sha = meta.get("sha256")
    if not sha:
        result.update(status="skipped", reason="missing sha256 in meta.json")
        return result

    async with SessionLocal() as db:
        existing = await _existing_version(db, sha)
        if existing and not force:
            result.update(
                status="skipped_duplicate",
                reason="content hash already ingested",
                document_id=str(existing.document_id),
                version_id=str(existing.id),
            )
            return result

        if dry_run:
            result.update(status="dry_run", format=meta.get("format"))
            return result

        # Re-ingest must reuse the existing document row and add a version.
        # Without this, every --force run creates a duplicate document.
        existing_doc = (
            await db.execute(
                select(KbDocument).where(
                    KbDocument.doc_metadata["source_id"].astext == source_id
                )
            )
        ).scalars().first()
        if existing_doc is None:
            doc_id = uuid.uuid4()
            next_version_no = 1
        else:
            doc_id = existing_doc.id
            current_max = await db.scalar(
                select(func.max(KbDocumentVersion.version_no)).where(
                    KbDocumentVersion.document_id == doc_id
                )
            )
            next_version_no = (current_max or 0) + 1
        version_id = uuid.uuid4()
        suffix = ".pdf" if meta.get("format") == "pdf" else ".html"
        relative = Path("documents") / str(doc_id) / str(version_id) / f"original{suffix}"
        target = settings.data_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)

        try:
            species = parse_species(",".join(meta.get("species") or []) or None)
        except ValueError:
            species = ["通用"]

        doc = None if existing_doc is not None else KbDocument(
            id=doc_id,
            title=(meta.get("resolved_title") or meta.get("title") or source_id)[:300],
            category=(meta.get("topics") or ["未分类"])[0],
            species=species,
            source_org=meta.get("publisher"),
            source_url=meta.get("url"),
            publish_year=_year(meta.get("publish_date") or meta.get("resolved_issued")),
            status="staging",
            source_type=meta.get("format") or "pdf",
            authority_level=meta.get("authority") or "unknown",
            verification_status="pending",
            fetched_at=datetime.fromisoformat(meta["fetched_at"])
            if meta.get("fetched_at")
            else None,
            effective_date=meta.get("effective_date"),
            growth_stages=list(meta.get("growth_stages") or []),
            region=meta.get("region"),
            doc_metadata={
                "source_id": source_id,
                "doc_type": meta.get("doc_type"),
                "license": meta.get("resolved_license") or meta.get("license"),
                "final_url": meta.get("final_url"),
                "requested_url": meta.get("requested_url"),
                "http_status": meta.get("http_status"),
                "robots": meta.get("robots"),
                "language": meta.get("language"),
                "size_bytes": meta.get("bytes"),
            },
        )
        version = KbDocumentVersion(
            id=version_id,
            document_id=doc_id,
            version_no=next_version_no,
            content_hash=sha,
            file_path=str(target),
            file_size=target.stat().st_size,
            status="processing",
            parser_name="trafilatura" if suffix == ".html" else "pymupdf",
        )
        job = KbIngestJob(
            id=uuid.uuid4(),
            document_version_id=version_id,
            job_type="ingest",
            status="queued",
            current_stage="queued",
            idempotency_key=f"ingest:{version_id}:v1",
        )
        if doc is not None:
            db.add(doc)
        else:
            existing_doc.verification_status = "pending"
        db.add_all([version, job])
        await db.commit()

    outcome = await ingest_version({}, str(version_id))

    async with SessionLocal() as db:
        chunk_count = await db.scalar(
            select(func.count())
            .select_from(KbChunk)
            .where(KbChunk.document_version_id == version_id)
        )
        version_row = await db.get(KbDocumentVersion, version_id)
        page_count = version_row.page_count if version_row else 0
        status = version_row.status if version_row else "unknown"

    meta["ingest"] = {
        "document_id": str(doc_id),
        "version_id": str(version_id),
        "status": status,
        "chunks": int(chunk_count or 0),
        "pages": page_count,
        "at": datetime.now(UTC).isoformat(),
    }
    (directory / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result.update(
        status="ingested" if status == "ready" else "ingest_failed",
        document_id=str(doc_id),
        version_id=str(version_id),
        chunks=int(chunk_count or 0),
        pages=page_count,
        pipeline=outcome.get("status"),
    )
    return result


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", default=str(ROOT / "data" / "inbox"))
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--report", default=str(ROOT / "data" / "reports" / "ingest_report.json"))
    parser.add_argument("--shard", default=None, metavar="I/N",
                        help="process only directories where sha16 %% N == I (1-indexed I)")
    args = parser.parse_args()

    await init_db()

    inbox = Path(args.inbox)
    directories = sorted(p for p in inbox.iterdir() if p.is_dir())
    if args.shard:
        idx, total = (int(x) for x in args.shard.split("/"))
        directories = [d for d in directories
                       if int(hashlib.sha256(d.name.encode()).hexdigest(), 16) % total == idx - 1]
    if args.only:
        wanted = set(args.only)
        directories = [d for d in directories if d.name in wanted]

    records = []
    for directory in directories:
        meta = _load_meta(directory)
        if meta is None:
            continue
        try:
            record = await ingest_one(directory, meta, dry_run=args.dry_run, force=args.force)
        except Exception as exc:  # one bad file must not abort the batch
            record = {
                "source_id": directory.name,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}"[:200],
            }

        records.append(record)
        detail = record.get("chunks") or record.get("reason") or record.get("error") or ""
        print(
            f"{record.get('status','?'):<18} {record.get('id','-'):<32} "
            f"pages={record.get('pages','-')} chunks={detail}"
            + (f" error={record.get('error')}" if record.get("error") else "")
        )

    ingested = [r for r in records if r["status"] == "ingested"]
    failed = [r for r in records if r.get("status") in {"ingest_failed", "failed"}]
    report = {
        "batch": "batch1",
        "at": datetime.now(UTC).isoformat(),
        "attempted": len(records),
        "ingested": len(ingested),
        "failed": len(failed),
        "skipped": sum(r["status"].startswith("skipped") for r in records),
        "documents": len(ingested),
        "chunks": sum(r.get("chunks", 0) for r in ingested),
        "parse_failure_rate": round(len(failed) / max(1, len(ingested) + len(failed)), 3),
        "records": records,
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\ningested={report['ingested']} failed={report['failed']} "
        f"skipped={report['skipped']} chunks={report['chunks']} -> {path}"
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))