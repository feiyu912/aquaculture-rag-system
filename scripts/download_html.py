#!/usr/bin/env python3
"""Download discovered HTML items (Chinese official sites) into data/inbox."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

import re

import httpx
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
INBOX = ROOT / "data" / "inbox"

PUBLISHERS = {
    "nftec-ybfk": "全国水产技术推广总站",
    "nftec-xzzx": "全国水产技术推广总站",
    "cafs-new-varieties": "中国水产科学研究院",
    "cafs-monographs": "中国水产科学研究院",
    "ffrc-kyjz": "中国水产科学研究院淡水渔业研究中心",
    "ffrc-jstg": "中国水产科学研究院淡水渔业研究中心",
}

RIGHTS_RE = re.compile(r"Creative\s+Commons[^<]{0,60}|Copyright[^<]{0,80}|版权所有[^<]{0,40}|不得转载[^<]{0,40}", re.I)


def _rights_of(html: str) -> str | None:
    """Return the licence/copyright string the page itself declares, if any."""
    match = RIGHTS_RE.search(html)
    return match.group(0).strip()[:120] if match else None


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 AquacultureResearch/1.0"


async def main(limit: int, source: str) -> int:
    from app.db import SessionLocal, init_db

    await init_db()
    async with SessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id,url,title FROM data_items WHERE state='discovered' AND source_id=:s "
            "ORDER BY url LIMIT :n"
        ), {"s": source, "n": limit})).all()

    ok = bad = 0
    async with httpx.AsyncClient(timeout=40, follow_redirects=True, headers={"User-Agent": UA}) as client:
        for item_id, url, title in rows:
            try:
                r = await client.get(url)
                html = r.text
                status = r.status_code
            except Exception as exc:  # noqa: BLE001
                html, status = "", f"{type(exc).__name__}"
            async with SessionLocal() as db:
                if status != 200 or len(html) < 800:
                    bad += 1
                    await db.execute(text(
                        "UPDATE data_items SET state='failed', attempts=attempts+1, last_error=:e, updated_at=now() WHERE id=:i"
                    ), {"e": f"http_{status}", "i": item_id})
                    await db.commit()
                    continue
                sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
                slug = sha[:16]
                target = INBOX / slug
                target.mkdir(parents=True, exist_ok=True)
                (target / "original.html").write_text(html, encoding="utf-8")
                rights = _rights_of(html)
                (target / "meta.json").write_text(json.dumps({
                    "url": url, "final_url": str(r.url), "title": title, "format": "html",
                    "sha256": sha, "bytes": len(html), "license": rights,
                    "publisher": PUBLISHERS.get(source, source),
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "authority": "official_technical" if source.startswith(("nftec", "agri", "cafs", "ffrc")) else "international",
                }, ensure_ascii=False, indent=2))
                await db.execute(text(
                    "UPDATE data_items SET state='downloaded', sha256=:s, bytes=:b, fetched_at=now(), "
                    "attempts=attempts+1, updated_at=now() WHERE id=:i"
                ), {"s": sha, "b": len(html), "i": item_id})
                await db.commit()
                ok += 1
            time.sleep(2.0)
            print(f"{ok+bad}/{len(rows)} {status} {slug[:10]}")
    print(f"downloaded={ok} failed={bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(int(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "nftec-ybfk")))
