#!/usr/bin/env python3
"""Harvest the per-item rights statement for WorldFish repository documents.

The stored `metadata.license` field is a constant written by our downloader
("repository-open-access"), not a publisher statement, so it cannot support a
licence decision. The repository's OAI-PMH endpoint exposes the real per-item
`dc:rights` (CC BY, CC BY-NC, all rights reserved, or nothing).

This script asks the OAI endpoint for metadata only, one item at a time, and
caches the answer. Re-running only fetches documents missing from the cache.

Output: data/reports/worldfish_rights.json
  [{"document_id": ..., "handle": ..., "rights": [...], "status": "ok"}]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

OUT = ROOT / "data" / "reports" / "worldfish_rights.json"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)


async def worldfish_docs() -> list[tuple[str, str]]:
    from sqlalchemy import text

    from app.db import SessionLocal

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id::text, source_url FROM kb_documents "
                    "WHERE status='active' AND source_org='WorldFish' ORDER BY id"
                )
            )
        ).all()
    return [(str(r[0]), r[1]) for r in rows]


def fetch(document_id: str, url: str, retries: int = 2) -> dict:
    handle = url.rstrip("/").rsplit("/", 1)[-1]
    endpoint = (
        "https://digitalarchive.worldfishcenter.org/server/oai/request"
        "?verb=GetRecord&metadataPrefix=oai_dc"
        f"&identifier=oai:digitalarchive.worldfishcenter.org:20.500.12348/{handle}"
    )
    last = ""
    for _ in range(retries + 1):
        proc = subprocess.run(
            ["curl", "-s", "-m", "25", "-A", UA, endpoint],
            capture_output=True, text=True, check=False,
        )
        body = proc.stdout
        if "GetRecord" in body or "idDoesNotExist" in body or "cannotDisseminateFormat" in body:
            rights = re.findall(
                r"<dc:(?:rights|license)[^>]*>(.*?)</dc:(?:rights|license)>", body, re.DOTALL
            )
            return {
                "document_id": document_id,
                "handle": handle,
                "rights": [r.strip() for r in rights if r.strip()],
                "status": "ok",
            }
        last = f"http {proc.returncode} bytes {len(body)}"
        time.sleep(1.5)
    return {"document_id": document_id, "handle": handle, "rights": [], "status": f"error: {last}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    docs = asyncio.run(worldfish_docs())
    cached: dict[str, dict] = {}
    if args.out.exists():
        for row in json.loads(args.out.read_text(encoding="utf-8")):
            cached[row["document_id"]] = row

    todo = [(doc_id, url) for doc_id, url in docs if doc_id not in cached]
    print(f"worldfish docs {len(docs)}, cached {len(cached)}, to fetch {len(todo)}")
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, row in enumerate(pool.map(lambda item: fetch(*item), todo)):
            cached[row["document_id"]] = row
            if index % 100 == 0:
                print(f"  fetched {index} ({time.time() - started:.0f}s)", file=sys.stderr)

    ordered = [cached[doc_id] for doc_id, _ in docs if doc_id in cached]
    args.out.write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding="utf-8")

    dist = Counter(
        (row["rights"][0] if row["rights"] else "(none)") for row in ordered
    )
    print("rights distribution:")
    for value, n in dist.most_common():
        print(f"  {n:4d}  {value}")
    errors = sum(1 for row in ordered if row["status"] != "ok")
    print(f"errors {errors}; wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())