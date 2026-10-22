#!/usr/bin/env python3
"""Discover items from a DSpace 7 repository REST API into ``data_items``.

Only enumerates metadata (title, handle, date, doi); document bodies are left to
the download stage.  Throttled to one request per second.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

API = "/server/api/discover/search/objects"


def _meta(item: dict, key: str) -> str | None:
    vals = (item.get("metadata") or {}).get(key) or []
    return vals[0].get("value") if vals else None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://digitalarchive.worldfishcenter.org")
    ap.add_argument("--query", default="aquaculture")
    ap.add_argument("--pages", type=int, default=4)
    ap.add_argument("--size", type=int, default=25)
    ap.add_argument("--source-id", default="worldfish-dspace")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        for page in range(args.pages):
            resp = await client.get(
                args.base + API,
                params={"query": args.query, "size": args.size, "page": page},
            )
            if resp.status_code != 200:
                print(f"page={page} HTTP {resp.status_code}; stopping")
                break
            data = resp.json()
            objs = data.get("_embedded", {}).get("searchResult", {}).get("_embedded", {}).get("objects", [])
            if not objs:
                break
            for obj in objs:
                item = obj.get("_embedded", {}).get("indexableObject", {})
                handle = item.get("handle")
                if not handle:
                    continue
                rows.append(
                    {
                        "url": f"{args.base}/handle/{handle}",
                        "title": (item.get("name") or "")[:300],
                        "date": _meta(item, "dc.date.issued"),
                        "doi": _meta(item, "dc.identifier.doi"),
                        "type": _meta(item, "dc.type"),
                        "uuid": item.get("uuid"),
                        "lang": _meta(item, "dc.language"),
                    }
                )
            print(f"page={page} items={len(objs)} cumulative={len(rows)}")
            time.sleep(1.0)

    allowed = {
        "Journal Article", "Report", "Book Chapter", "Thesis",
        "Training Material", "Brief", "Book", "Technical Report",
    }
    before = len(rows)
    rows = [
        r for r in rows
        if (r.get("type") or "") in allowed and (r.get("date") or "9999") >= "2000"
    ]
    print(f"type/year filter: {before} -> {len(rows)}")

    if args.dry_run:
        print(f"dry-run rows={len(rows)}")
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
    from sqlalchemy import text
    from app.db import SessionLocal, init_db

    await init_db()
    async with SessionLocal() as db:
        added = 0
        for row in rows:
            res = await db.execute(
                text(
                    "INSERT INTO data_items (source_id,url,title,kind,state,license,meta) "
                    "VALUES (:s,:u,:t,'pdf','selected',:l,:m) "
                    "ON CONFLICT (url) DO NOTHING"
                ),
                {
                    "s": args.source_id,
                    "u": row["url"],
                    "t": row["title"],
                    "l": "repository-open-access",
                    "m": json.dumps({k: v for k, v in row.items() if k != "url"}),
                },
            )
            added += res.rowcount or 0
        await db.commit()
        total = (await db.execute(text("SELECT count(*) FROM data_items WHERE state='discovered'"))).scalar()
        print(f"inserted={added} discovered_total={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
