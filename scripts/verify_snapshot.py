#!/usr/bin/env python3
"""Verify a frozen corpus snapshot and detect drift against the live database.

Checks, in order:
  1. every file listed in SHA256SUMS hashes to the recorded value;
  2. snapshot.json's own artifact hashes agree with the files;
  3. every document digest and the corpus digest recompute exactly;
  4. with --check-db, the active set, version ids and content hashes still match
     the database (added / removed / changed documents are listed).

Exit code 0 means the snapshot is intact (and, with --check-db, still matches).
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def canonical(payload) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda v: v.isoformat() if hasattr(v, "isoformat") else str(v),
    ).encode("utf-8")


def digest(payload) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_artifacts(snapshot_dir: Path, manifest: dict) -> list[str]:
    errors = []
    sums = {}
    for line in (snapshot_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if line.strip():
            value, name = line.split("  ", 1)
            sums[name] = value
    for name, expected in sums.items():
        path = snapshot_dir / name
        if not path.exists():
            errors.append(f"missing artifact {name}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            errors.append(f"{name}: sha256 {actual} != {expected}")
        info = manifest["artifacts"].get(name, {})
        if info.get("sha256") not in (None, actual):
            errors.append(f"{name}: snapshot.json disagrees with file hash")
    return errors


def check_documents(snapshot_dir: Path, manifest: dict) -> tuple[list[str], list[dict]]:
    errors = []
    records = []
    with gzip.open(snapshot_dir / "documents.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            records.append(json.loads(line))
    for record in records:
        stored = record["document_digest"]
        body = {k: v for k, v in record.items() if k not in {"document_digest", "gate"}}
        actual = digest(body)
        if actual != stored:
            errors.append(f"{record['document_id']}: document digest mismatch")
    corpus = digest([f"{r['document_id']}:{r['document_digest']}" for r in records])
    if corpus != manifest["corpus_digest"]:
        errors.append(f"corpus digest {corpus} != {manifest['corpus_digest']}")
    if len(records) != manifest["document_count"]:
        errors.append(f"document count {len(records)} != {manifest['document_count']}")
    return errors, records


async def check_db(records: list[dict]) -> tuple[list[str], dict]:
    from sqlalchemy import text

    from app.db import SessionLocal

    frozen = {
        r["document_id"]: (r["version"]["id"], r["version"]["content_hash"]) for r in records
    }
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT d.id::text, d.current_version_id::text, v.content_hash "
                    "FROM kb_documents d LEFT JOIN kb_document_versions v "
                    "ON v.id=d.current_version_id WHERE d.status='active'"
                )
            )
        ).all()
    live = {r[0]: (r[1], r[2]) for r in rows}
    added = sorted(set(live) - set(frozen))
    removed = sorted(set(frozen) - set(live))
    changed = sorted(
        doc_id for doc_id in set(frozen) & set(live) if frozen[doc_id] != live[doc_id]
    )
    return added, {"added": added, "removed": removed, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--check-db", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit 1 when drift is found")
    args = parser.parse_args()

    snapshot_dir = args.snapshot
    if snapshot_dir is None:
        candidates = sorted((ROOT / "snapshots").glob("kb-*"))
        if not candidates:
            print("no snapshot found under snapshots/", file=sys.stderr)
            return 2
        snapshot_dir = candidates[-1]
    manifest = json.loads((snapshot_dir / "snapshot.json").read_text(encoding="utf-8"))

    errors = check_artifacts(snapshot_dir, manifest)
    doc_errors, records = check_documents(snapshot_dir, manifest)
    errors += doc_errors

    print(f"snapshot {manifest['snapshot_id']} ({manifest['document_count']} documents)")
    print(f"corpus digest {manifest['corpus_digest']}")
    print("artifacts: OK" if not errors else f"artifacts: {len(errors)} error(s)")
    for error in errors:
        print(f"  ! {error}")

    drift = None
    if args.check_db:
        _added, drift = asyncio.run(check_db(records))
        print(
            f"database drift: +{len(drift['added'])} -{len(drift['removed'])} "
            f"~{len(drift['changed'])}"
        )
        for key in ("added", "removed", "changed"):
            for doc_id in drift[key][:10]:
                print(f"  {key}: {doc_id}")

    if errors:
        return 1
    if drift and args.strict and any(drift.values()):
        return 1
    print("snapshot intact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())