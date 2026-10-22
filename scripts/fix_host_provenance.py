#!/usr/bin/env python3
"""Resolve source_id for orphan docs from the inbox copy's original URL host."""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

HOST_MAP = [
    ("nftec.agri.cn", "nftec-ybfk"),
    ("cafs.ac.cn", "cafs-new-varieties"),
    ("ffrc.cn", "ffrc-jyjs"),
    ("worldfishcenter.org", "worldfish-dspace"),
    ("digitalarchive.worldfishcenter", "worldfish-dspace"),
    ("nyncw.sh.gov.cn", "sh-nyncw-bwbdscl"),
    ("hubei.gov.cn", "hb-nysy-yyjs"),
    ("gd.gov.cn", "gd-dara-tech"),
    ("nantong.gov.cn", "js-nantong-yyyz"),
    ("hunan.gov.cn", "hn-agri-jszn"),
    ("zj.gov.cn", "zj-nynct-dssc"),
    ("moa.gov.cn", "agri-national"),
]


def sid_for_url(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    for suffix, sid in HOST_MAP:
        if host.endswith(suffix):
            return sid
    return None


async def main(apply: bool) -> int:
    from sqlalchemy import text
    from app.db import SessionLocal, init_db

    await init_db()
    resolved, unresolved = [], []
    async with SessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, metadata->>'source_id' FROM kb_documents "
            "WHERE status='staging' AND source_trust='unknown'"))).all()
        for doc_id, sid in rows:
            meta_path = ROOT / "data" / "inbox" / str(sid) / "meta.json"
            url = None
            if meta_path.is_file():
                try:
                    url = json.loads(meta_path.read_text()).get("url")
                except Exception:
                    url = None
            new_sid = sid_for_url(url) if url else None
            (resolved if new_sid else unresolved).append((doc_id, sid, url, new_sid))
            if apply and new_sid:
                await db.execute(text(
                    "UPDATE kb_documents SET metadata = metadata || jsonb_build_object("
                    "'source_id', CAST(:s AS text), 'provenance_restored', 'host_map') "
                    "WHERE id = CAST(:d AS uuid)"),
                    {"s": new_sid, "d": doc_id})
        if apply:
            await db.commit()
    print("resolved", len(resolved), "unresolved", len(unresolved))
    for _, sid, url, new_sid in resolved[:5]:
        print("  ", sid, "->", new_sid, "|", (url or "")[:60])
    for _, sid, url, _ in unresolved[:5]:
        print("  UNRESOLVED", sid, "|", (url or "no url")[:60])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--apply" in sys.argv)))
