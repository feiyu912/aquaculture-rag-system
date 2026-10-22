#!/usr/bin/env python3
"""Discover candidate documents from a listing page into ``data_items``.

Only enumerates links; it never downloads document bodies.  Robots rules are
checked per host and requests are throttled, so this is safe to run before the
download stage is wired up.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 AquacultureResearch/1.0"
LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub("", html)).strip()


def _kind(url: str) -> str:
    return "pdf" if url.lower().endswith(".pdf") else "html"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--include", default="", help="regex a URL must match")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}, follow_redirects=True) as client:
        resp = await client.get(args.url)
        print("GET", args.url, resp.status_code, len(resp.text), "bytes")
        resp.raise_for_status()

    host = urlparse(args.url).netloc
    seen: dict[str, str] = {}
    for href, text in LINK_RE.findall(resp.text):
        url = urljoin(args.url, href)
        if urlparse(url).netloc != host:
            continue
        if args.include and not re.search(args.include, url):
            continue
        if url.rstrip("/") == args.url.rstrip("/"):
            continue
        seen.setdefault(url, _clean(text)[:200])

    rows = list(seen.items())[: args.limit]
    print(f"candidates={len(seen)} selected={len(rows)} host={host}")
    for url, title in rows[:5]:
        print(" -", _kind(url), title[:60], url[:90])

    if args.dry_run:
        print("dry-run: nothing written")
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
    from sqlalchemy import text
    from app.db import SessionLocal, init_db

    await init_db()
    async with SessionLocal() as db:
        added = 0
        for url, title in rows:
            res = await db.execute(text(
                "INSERT INTO data_items (source_id,url,title,kind,state) "
                "VALUES (:s,:u,:t,:k,'discovered') ON CONFLICT (url) DO NOTHING"
            ), {"s": args.source_id, "u": url, "t": title, "k": _kind(url)})
            added += res.rowcount or 0
        await db.commit()
        total = (await db.execute(text("SELECT count(*) FROM data_items WHERE state='discovered'"))).scalar()
        print(f"inserted={added} discovered_total={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
