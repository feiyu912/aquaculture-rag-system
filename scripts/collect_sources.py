#!/usr/bin/env python3
"""Fetch the curated source registry into ``data/inbox/<id>/``.

Each item produces ``original.pdf|html`` plus ``meta.json`` with the full
provenance record (final URL, status, sha256, fetch time, robots decision,
licence, authority level).  Nothing is written to the knowledge base here: the
separate ``ingest_inbox.py`` step imports into *staging*.

Usage:
    uv run python ../../scripts/collect_sources.py --limit 5 --dry-run
    uv run python ../../scripts/collect_sources.py --only wf-pond-aeration
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.collection.fetch import FetchError, fetch  # noqa: E402
from app.collection.registry import SourceSpec, load_registry  # noqa: E402
from app.collection.resolvers import ResolveError, resolve  # noqa: E402
from app.ingestion.format import detect_format  # noqa: E402


async def collect_one(spec: SourceSpec, out_dir: Path, dry_run: bool) -> dict:
    record: dict = {"id": spec.id, "policy": spec.policy, "status": "pending"}
    if spec.policy == "manual":
        record.update(
            status="skipped_manual",
            reason="source policy is manual (robots or no automated channel)",
        )
        return record

    try:
        resolved = await resolve(spec)
    except ResolveError as exc:
        record.update(status="resolve_failed", error=str(exc)[:300])
        return record

    record["resolved_url"] = resolved.url
    if dry_run:
        record.update(status="dry_run", title=resolved.title, license=resolved.license)
        return record

    try:
        result = await fetch(resolved.url)
    except FetchError as exc:
        record.update(status="fetch_failed", error=str(exc)[:300])
        return record

    fmt = detect_format(result.body, content_type=result.content_type)
    if fmt is None:
        fmt = spec.format_hint() or "html"

    target_dir = out_dir / spec.id
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".pdf" if fmt == "pdf" else ".html"
    (target_dir / f"original{suffix}").write_bytes(result.body)

    meta = {
        **spec.as_dict(),
        "format": fmt,
        "fetched_at": result.fetched_at.isoformat(),
        "http_status": result.status,
        "content_type": result.content_type,
        "bytes": result.size,
        "sha256": result.sha256,
        "final_url": result.final_url,
        "requested_url": result.url,
        "robots": result.robots.as_dict(),
        "resolved_title": resolved.title,
        "resolved_issued": resolved.issued,
        "resolved_license": resolved.license,
    }
    (target_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record.update(
        status="collected",
        format=fmt,
        bytes=result.size,
        sha256=result.sha256[:12],
        title=resolved.title or spec.title,
        license=resolved.license or spec.license,
    )
    return record


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry", default=str(ROOT / "data" / "sources" / "registry.yaml")
    )
    parser.add_argument("--out", default=str(ROOT / "data" / "inbox"))
    parser.add_argument("--only", nargs="*", default=None, help="source ids")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--report", default=str(ROOT / "data" / "reports" / "collect_report.json")
    )
    args = parser.parse_args()

    specs = load_registry(args.registry)
    if args.only:
        wanted = set(args.only)
        specs = [s for s in specs if s.id in wanted]
        missing = wanted - {s.id for s in specs}
        if missing:
            print(f"unknown ids: {sorted(missing)}", file=sys.stderr)
    if args.limit:
        specs = specs[: args.limit]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(UTC)
    records = []
    for spec in specs:
        record = await collect_one(spec, out_dir, args.dry_run)
        records.append(record)
        line = f"{record['status']:<16} {spec.id:<32} {spec.authority:<18}"
        detail = record.get("title") or record.get("error") or record.get("reason") or ""
        print(f"{line} {str(detail)[:60]}")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "total": len(records),
        "collected": sum(r["status"] == "collected" for r in records),
        "skipped_manual": sum(r["status"] == "skipped_manual" for r in records),
        "failed": sum(r["status"].endswith("failed") for r in records),
        "records": records,
    }
    report_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"\ncollected={summary['collected']} skipped={summary['skipped_manual']} "
        f"failed={summary['failed']} -> {report_path}"
    )
    await _record_run(
        kind="crawl",
        params={"registry": args.registry, "only": args.only, "limit": args.limit},
        stats={key: value for key, value in summary.items() if key != "records"},
        started_at=started_at,
    )
    return 0


async def _record_run(*, kind: str, params: dict, stats: dict, started_at) -> None:
    """Best-effort audit row; a missing DB must not fail the collection run."""
    try:
        from app.db import SessionLocal, init_db
        from app.models import DataRun

        await init_db()
        async with SessionLocal() as db:
            db.add(
                DataRun(
                    kind=kind,
                    status="succeeded",
                    params=params,
                    stats=stats,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"warn: DataRun not recorded: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))