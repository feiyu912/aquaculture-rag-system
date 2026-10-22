#!/usr/bin/env python3
"""Download selected DSpace items into data/inbox and record provenance."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, UTC
from pathlib import Path

import httpx
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
BASE = "https://digitalarchive.worldfishcenter.org"
INBOX = ROOT / "data" / "inbox"


async def fetch_pdf(client: httpx.AsyncClient, uuid: str):
    b = (await client.get(f"{BASE}/server/api/core/items/{uuid}/bundles")).json()
    orig = [x for x in b.get("_embedded", {}).get("bundles", []) if x.get("name") == "ORIGINAL"]
    if not orig:
        return None, "no_original_bundle"
    bs = (await client.get(orig[0]["_links"]["bitstreams"]["href"])).json()
    pdfs = [x for x in bs.get("_embedded", {}).get("bitstreams", []) if (x.get("name") or "").lower().endswith(".pdf")]
    if not pdfs:
        return None, "no_pdf_bitstream"
    r = await client.get(pdfs[0]["_links"]["content"]["href"])
    if r.status_code != 200 or r.content[:4] != b"%PDF":
        return None, f"bad_response_{r.status_code}"
    return (pdfs[0]["name"], r.content), None


async def main(limit: int) -> int:
    from app.db import SessionLocal, init_db

    await init_db()
    async with SessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id,url,title,meta->>'uuid' FROM data_items "
            "WHERE state='selected' AND meta->>'uuid' IS NOT NULL ORDER BY url LIMIT :n"
        ), {"n": limit})).all()

    ok = bad = 0
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        for item_id, url, title, uuid in rows:
            try:
                got, err = await fetch_pdf(client, uuid)
            except Exception as exc:  # noqa: BLE001
                got, err = None, f"{type(exc).__name__}"
            async with SessionLocal() as db:
                if not got:
                    bad += 1
                    await db.execute(text(
                        "UPDATE data_items SET state='failed', attempts=attempts+1, last_error=:e, updated_at=now() WHERE id=:i"
                    ), {"e": err, "i": item_id})
                    await db.commit()
                    continue
                name, content = got
                sha = hashlib.sha256(content).hexdigest()
                slug = sha[:16]
                target = INBOX / slug
                target.mkdir(parents=True, exist_ok=True)
                (target / "original.pdf").write_bytes(content)
                (target / "meta.json").write_text(json.dumps({
                    "url": url, "final_url": url, "title": title, "format": "pdf",
                    "sha256": sha, "bytes": len(content), "license": "repository-open-access",
                    "publisher": "WorldFish", "fetched_at": datetime.now(UTC).isoformat(),
                    "authority": "international", "filename": name,
                }, ensure_ascii=False, indent=2))
                await db.execute(text(
                    "UPDATE data_items SET state='downloaded', sha256=:s, bytes=:b, "
                    "fetched_at=now(), attempts=attempts+1, updated_at=now() WHERE id=:i"
                ), {"s": sha, "b": len(content), "i": item_id})
                await db.commit()
                ok += 1
            print(f"{ok+bad}/{len(rows)} {'ok ' if got else 'ERR'} {sha[:10] if got else err}")
    print(f"downloaded={ok} failed={bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)))
