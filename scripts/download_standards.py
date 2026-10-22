#!/usr/bin/env python3
"""Discover and download current (现行) SC/T and DB aquaculture standards.

The two SAC/INFO platforms expose public search and PDF endpoints:

* 行业标准 (SC/T, NY/T, ...): https://hbba.sacinfo.org.cn
* 地方标准 (DB**):            https://dbba.sacinfo.org.cn

``stdQueryList`` is a form-encoded POST returning JSON; ``portal/download/<pk>``
returns ``application/pdf`` without login.  This script only touches those two
public endpoints.  GB standards are deliberately out of scope: openstd's
download button is CAPTCHA-gated and its preview is image-only.

Output per standard::

    data/inbox/<sha16>/original.pdf
    data/inbox/<sha16>/meta.json

and one ``data_items`` row with ``source_id='std-sc'`` (行业) or ``'std-db'``
(地方), ``state='downloaded'``.  Nothing is ingested here; run
``ingest_inbox.py`` separately.

Usage (from ``apps/api``)::

    uv run python ../../scripts/download_standards.py --dry-run
    uv run python ../../scripts/download_standards.py --sc-limit 20 --db-limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import re
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
INBOX = ROOT / "data" / "inbox"

KEYWORDS = ("水产", "鱼", "虾", "蟹", "贝", "藻", "养殖", "饲料", "尾水", "病害")
PLATFORMS = {
    "std-sc": "https://hbba.sacinfo.org.cn",  # 行业标准
    "std-db": "https://dbba.sacinfo.org.cn",  # 地方标准
}
PLATFORM_NAMES = {"std-sc": "hbba", "std-db": "dbba"}
PLATFORM_LABELS = {"std-sc": "行业标准", "std-db": "地方标准"}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
CST = ZoneInfo("Asia/Shanghai")

# The generic keywords (养殖/饲料/病害/尾水) also match livestock and crop
# standards, so the pilot only keeps titles with an explicitly aquatic token.
AQUATIC_TITLE_RE = re.compile(
    r"水产|渔业|渔|鱼|虾|蟹|贝|藻|水生|稻渔|池塘|网箱|对虾|鲍|海参|珍珠|"
    r"龟|鳖|蛙|螺|蛏|蛤|牡蛎|扇贝|海带|紫菜|裙带菜|鱼粉|鱼油"
)


def _ms_date(value: object) -> str | None:
    """Decode a platform epoch-millisecond date to a Beijing calendar date.

    The timestamps are midnight Beijing time (16:00 UTC the previous day), so
    a UTC conversion would shift every date one day back.
    """
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=CST).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _publisher(platform: str, record: dict) -> str | None:
    if platform == "std-sc":
        return "农业农村部"
    dept = (record.get("chargeDept") or "").strip()
    if dept:
        return dept
    province = (record.get("industry") or "").strip()
    return f"{province}市场监督管理局" if province else None


def _normalise(platform: str, record: dict) -> dict:
    number = (record.get("code") or "").strip()
    name = (record.get("chName") or "").strip()
    issued = _ms_date(record.get("issueDate"))
    effective = _ms_date(record.get("actDate"))
    detail_url = f"{PLATFORMS[platform]}/stdDetail/{record['pk']}"
    download_url = f"{PLATFORMS[platform]}/portal/download/{record['pk']}"
    return {
        "pk": record["pk"],
        "source_id": platform,
        "platform": PLATFORM_NAMES[platform],
        "number": number,
        "name": name,
        "title": f"{number} {name}".strip(),
        "status": (record.get("status") or "").strip(),
        "issued": issued,
        "effective": effective,
        "replaces": (record.get("reviseStdCodes") or "").strip() or None,
        "charge_dept": (record.get("chargeDept") or "").strip() or None,
        "industry": (record.get("industry") or "").strip() or None,
        "publisher": _publisher(platform, record),
        "region": "全国" if platform == "std-sc" else (record.get("industry") or None),
        "detail_url": detail_url,
        "download_url": download_url,
    }


class Throttle:
    """Start-to-start spacing for every outbound request (>= 2 s)."""

    def __init__(self, seconds: float) -> None:
        self.seconds = max(seconds, 2.0)
        self._last = 0.0

    async def wait(self) -> None:
        delay = self._last + self.seconds - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        self._last = time.monotonic()


async def _post_json(
    client: httpx.AsyncClient, throttle: Throttle, url: str, data: dict, referer: str
) -> dict:
    last_error: Exception | None = None
    for attempt in range(4):
        await throttle.wait()
        response = await client.post(
            url,
            data=data,
            headers={
                "Referer": referer,
                # Without the XHR marker the edge occasionally answers a POST
                # with the HTML home page and HTTP 200 instead of JSON.
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "text/json, application/json, text/javascript, */*; q=0.01",
            },
        )
        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            if "json" in content_type:
                try:
                    return response.json()
                except ValueError as exc:
                    last_error = exc
            else:
                last_error = RuntimeError(f"non_json:{content_type}")
        elif response.status_code in (429, 500, 502, 503, 504):
            last_error = RuntimeError(f"http_{response.status_code}")
        else:
            response.raise_for_status()
        if attempt < 3:
            await asyncio.sleep(5 * (attempt + 1))
    raise RuntimeError(f"search failed: {last_error}")


async def _get(
    client: httpx.AsyncClient, throttle: Throttle, url: str, referer: str
) -> httpx.Response:
    for attempt in range(3):
        await throttle.wait()
        response = await client.get(
            url, headers={"Referer": referer, "Accept": "application/pdf,*/*"}
        )
        if response.status_code < 500:
            return response
        if attempt < 2:
            await asyncio.sleep(5 * (attempt + 1))
    return response


async def discover_platform(
    client: httpx.AsyncClient,
    throttle: Throttle,
    platform: str,
    keywords: tuple[str, ...],
    today: date,
) -> dict:
    base = PLATFORMS[platform]
    seen: dict[str, dict] = {}
    per_keyword: dict[str, dict] = {}
    requests = 0

    for keyword in keywords:
        first = await _post_json(
            client,
            throttle,
            f"{base}/stdQueryList",
            {"current": 1, "size": 200, "key": keyword},
            f"{base}/",
        )
        requests += 1
        total = int(first.get("total") or 0)
        size = int(first.get("size") or 10)
        pages = max(1, math.ceil(total / max(size, 1)))
        records = list(first.get("records") or [])

        for page in range(2, pages + 1):
            payload = await _post_json(
                client,
                throttle,
                f"{base}/stdQueryList",
                {"current": page, "size": size, "key": keyword},
                f"{base}/",
            )
            requests += 1
            records.extend(payload.get("records") or [])

        keyword_seen: dict[str, dict] = {}
        for record in records:
            if not record.get("pk"):
                continue
            keyword_seen[record["pk"]] = _normalise(platform, record)
            seen[record["pk"]] = keyword_seen[record["pk"]]

        current = [item for item in keyword_seen.values() if item["status"] == "现行"]
        effective = [
            item
            for item in current
            if item["effective"] and item["effective"] <= today.isoformat()
        ]
        per_keyword[keyword] = {
            "platform_total": total,
            "fetched": len(keyword_seen),
            "current": len(current),
            "current_effective": len(effective),
        }

    all_items = list(seen.values())
    current_all = [item for item in all_items if item["status"] == "现行"]
    current_effective = [
        item
        for item in current_all
        if item["effective"] and item["effective"] <= today.isoformat()
    ]
    stats = {
        "raw_unique": len(all_items),
        "status_current": len(current_all),
        "current_effective": len(current_effective),
        "requests": requests,
        "per_keyword": per_keyword,
        "current_effective_sct": sum(
            1 for item in current_effective if item["number"].upper().startswith("SC/T")
        ),
        "current_effective_aquatic_title": sum(
            1 for item in current_effective if AQUATIC_TITLE_RE.search(item["name"])
        ),
    }
    return {"stats": stats, "records": current_effective}


def _select_candidates(
    platform: str, records: list[dict], limit: int, max_attempts: int, seed: int
) -> list[dict]:
    if platform == "std-sc":
        pool = [item for item in records if item["number"].upper().startswith("SC/T")]
    else:
        pool = [item for item in records if AQUATIC_TITLE_RE.search(item["name"])]
    # Stable base order before shuffling keeps the sample reproducible even if
    # the platform returns records in a different order.
    pool.sort(key=lambda item: (item["effective"] or "", item["number"]))
    random.Random(seed).shuffle(pool)
    return pool[: max(max_attempts, limit)]


def _pdf_stats(body: bytes) -> tuple[int, int]:
    document = pymupdf.open(stream=body, filetype="pdf")
    try:
        pages = document.page_count
        chars = sum(len(page.get_text("text")) for page in document)
    finally:
        document.close()
    return pages, chars


async def _existing_urls() -> tuple[set[str], set[str]]:
    from sqlalchemy import text

    from app.db import SessionLocal

    urls: set[str] = set()
    details: set[str] = set()
    async with SessionLocal() as db:
        rows = (
            await db.execute(text("SELECT url, meta->>'detail_url' FROM data_items"))
        ).all()
    for url, detail in rows:
        if url:
            urls.add(url)
        if detail:
            details.add(detail)
    return urls, details


async def _insert_item(meta: dict, item: dict) -> str | None:
    from sqlalchemy import text

    from app.db import SessionLocal

    async with SessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "INSERT INTO data_items "
                    "(source_id, url, final_url, title, kind, license, sha256, state, bytes, "
                    " fetched_at, meta) "
                    "VALUES (:source_id, :url, :final_url, :title, 'pdf', "
                    " CAST(:license AS varchar), :sha256, 'downloaded', :bytes, now(), "
                    " CAST(:meta AS jsonb)) "
                    "ON CONFLICT (url) DO NOTHING RETURNING id"
                ),
                {
                    "source_id": item["source_id"],
                    "url": meta["url"],
                    "final_url": meta["final_url"],
                    "title": meta["title"],
                    "license": meta["license"],
                    "sha256": meta["sha256"],
                    "bytes": meta["bytes"],
                    "meta": json.dumps(meta, ensure_ascii=False),
                },
            )
        ).scalar()
        await db.commit()
    return str(row) if row else None


async def download_platform(
    client: httpx.AsyncClient,
    throttle: Throttle,
    platform: str,
    candidates: list[dict],
    limit: int,
    max_attempts: int,
    inbox: Path,
    existing_urls: set[str],
    existing_details: set[str],
) -> dict:
    result: dict = {
        "platform": PLATFORM_NAMES[platform],
        "label": PLATFORM_LABELS[platform],
        "source_id": platform,
        "target": limit,
        "attempted": 0,
        "downloaded": 0,
        "failed": 0,
        "skipped_existing": 0,
        "bytes": 0,
        "text_layer": {"usable": 0, "needs_ocr": 0, "empty": 0},
        "failures": [],
        "items": [],
    }
    for item in candidates:
        if result["downloaded"] >= limit or result["attempted"] >= max_attempts:
            break
        if item["download_url"] in existing_urls or item["detail_url"] in existing_details:
            result["skipped_existing"] += 1
            continue

        result["attempted"] += 1
        label = f"{item['title']} [{item['number']}]"
        try:
            response = await _get(
                client, throttle, item["download_url"], item["detail_url"]
            )
            if response.status_code != 200:
                raise RuntimeError(f"http_{response.status_code}")
            body = response.content
            if not body.startswith(b"%PDF"):
                raise RuntimeError(f"not_pdf:{response.headers.get('content-type')}")
            if len(body) < 1024:
                raise RuntimeError(f"too_small:{len(body)}")
            pages, chars = await asyncio.to_thread(_pdf_stats, body)
        except Exception as exc:  # one bad standard must not abort the pilot
            result["failed"] += 1
            result["failures"].append(
                {"number": item["number"], "title": item["name"], "error": str(exc)[:200]}
            )
            print(f"  FAIL {label}: {exc}")
            continue

        sha = hashlib.sha256(body).hexdigest()
        slug = sha[:16]
        target = inbox / slug
        target.mkdir(parents=True, exist_ok=True)
        (target / "original.pdf").write_bytes(body)

        needs_ocr = chars <= 200
        meta = {
            "url": item["download_url"],
            "final_url": str(response.url),
            "title": item["title"],
            "format": "pdf",
            "sha256": sha,
            "bytes": len(body),
            # The platform states no licence for the standard text; the detail
            # page only carries a site-wide "版权所有 侵权必究" footer.
            "license": None,
            "license_note": "平台未声明标准文本使用许可（详情页仅有站点版权声明）",
            "publisher": item["publisher"],
            "authority": "official_standard",
            "fetched_at": datetime.now(UTC).isoformat(),
            "http_status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "detail_url": item["detail_url"],
            "doc_type": "standard",
            "language": "zh",
            "topics": ["水产标准"],
            "publish_date": item["issued"],
            "effective_date": item["effective"],
            "region": item["region"],
            "pages": pages,
            "text_chars": chars,
            "standard": {
                "number": item["number"],
                "title": item["name"],
                "status": item["status"],
                "issued": item["issued"],
                "effective": item["effective"],
                "replaces": item["replaces"],
                "platform": item["platform"],
            },
        }
        (target / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        data_item_id = await _insert_item(meta, item)

        existing_urls.add(item["download_url"])
        existing_details.add(item["detail_url"])
        result["downloaded"] += 1
        result["bytes"] += len(body)
        result["text_layer"]["needs_ocr" if needs_ocr else "usable"] += 1
        if chars == 0:
            result["text_layer"]["empty"] += 1
        result["items"].append(
            {
                "number": item["number"],
                "title": item["name"],
                "effective": item["effective"],
                "url": item["download_url"],
                "detail_url": item["detail_url"],
                "sha256": sha,
                "bytes": len(body),
                "pages": pages,
                "text_chars": chars,
                "text_layer": "needs_ocr" if needs_ocr else "usable",
                "data_item_id": data_item_id,
            }
        )
        print(
            f"  OK   {label} bytes={len(body)} pages={pages} chars={chars}"
            f"{' NEEDS_OCR' if needs_ocr else ''}"
        )
    return result


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sc-limit", type=int, default=20)
    parser.add_argument("--db-limit", type=int, default=20)
    parser.add_argument("--max-attempts", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--out", default=str(INBOX))
    parser.add_argument(
        "--report",
        default=str(ROOT / "data" / "reports" / "download_standards.json"),
    )
    parser.add_argument(
        "--catalog",
        default=str(ROOT / "data" / "reports" / "standards_catalog.json"),
    )
    parser.add_argument("--rate", type=float, default=2.1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    today = datetime.now(CST).date()
    inbox = Path(args.out)
    inbox.mkdir(parents=True, exist_ok=True)
    throttle = Throttle(args.rate)

    limits = {"std-sc": args.sc_limit, "std-db": args.db_limit}
    discovery: dict[str, dict] = {}
    catalogs: dict[str, list[dict]] = {}
    selected: dict[str, list[dict]] = {}
    async with httpx.AsyncClient(
        timeout=120, follow_redirects=True, headers={"User-Agent": UA}
    ) as client:
        for platform in ("std-sc", "std-db"):
            print(
                f"discovering {PLATFORM_LABELS[platform]} "
                f"({PLATFORM_NAMES[platform]}) ..."
            )
            found = await discover_platform(client, throttle, platform, KEYWORDS, today)
            discovery[platform] = found["stats"]
            catalogs[platform] = found["records"]
            stats = found["stats"]
            print(
                f"  raw={stats['raw_unique']} current={stats['status_current']} "
                f"current+effective={stats['current_effective']} "
                f"sct={stats['current_effective_sct']} "
                f"aquatic_title={stats['current_effective_aquatic_title']}"
            )
            selected[platform] = _select_candidates(
                platform,
                found["records"],
                limits[platform],
                args.max_attempts,
                args.seed,
            )

        catalog_path = Path(args.catalog)
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(UTC).isoformat(),
                    "today": today.isoformat(),
                    "keywords": list(KEYWORDS),
                    "platforms": {
                        platform: {
                            "stats": discovery[platform],
                            "records": [
                                {
                                    key: item[key]
                                    for key in (
                                        "number",
                                        "name",
                                        "status",
                                        "issued",
                                        "effective",
                                        "replaces",
                                        "detail_url",
                                    )
                                }
                                for item in catalogs[platform]
                            ],
                        }
                        for platform in ("std-sc", "std-db")
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        pilot: dict[str, dict] = {}
        if not args.dry_run:
            from app.db import init_db

            await init_db()
            existing_urls, existing_details = await _existing_urls()
            for platform in ("std-sc", "std-db"):
                print(f"downloading {PLATFORM_LABELS[platform]} pilot ...")
                pilot[platform] = await download_platform(
                    client,
                    throttle,
                    platform,
                    selected[platform],
                    limits[platform],
                    args.max_attempts,
                    inbox,
                    existing_urls,
                    existing_details,
                )

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "today": today.isoformat(),
        "keywords": list(KEYWORDS),
        "rate_limit_seconds": max(args.rate, 2.0),
        "dry_run": args.dry_run,
        "selection": {
            "method": "deterministic shuffle (seed) of current+effective hits; "
            "SC/T codes for 行业, aquatic-title hits for 地方; failed downloads are "
            "backfilled until the target is reached",
            "seed": args.seed,
            "max_attempts_per_platform": args.max_attempts,
            "sc_limit": args.sc_limit,
            "db_limit": args.db_limit,
        },
        "discovery": discovery,
        "pilot": pilot,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n== discovery ==")
    for platform in ("std-sc", "std-db"):
        stats = discovery[platform]
        print(
            f"{PLATFORM_LABELS[platform]:<6} current+effective={stats['current_effective']} "
            f"(SC/T={stats['current_effective_sct']}, "
            f"aquatic-title={stats['current_effective_aquatic_title']})"
        )
    if not args.dry_run:
        print("== pilot ==")
        for platform in ("std-sc", "std-db"):
            item = pilot[platform]
            print(
                f"{PLATFORM_LABELS[platform]:<6} downloaded={item['downloaded']}/"
                f"{item['target']} failed={item['failed']} "
                f"attempted={item['attempted']} bytes={item['bytes']} "
                f"text={item['text_layer']['usable']} "
                f"ocr={item['text_layer']['needs_ocr']}"
            )
    print(f"-> {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))