#!/usr/bin/env python3
"""Harvest open-access full text from two CC BY-NC-ND 4.0 Chinese journals.

Both journals run the same (QinYun / RHHZ) platform, so one harvester serves
both:

    水产学报          https://www.china-fishery.com/scxuebao/        source_id jfc-oa
    渔业科学进展      https://journal.yykxjz.cn/yykxjz/              source_id pfs-oa

Listing URLs are server-rendered and enumerable:

    issue TOC      <site>/article/issue/<year>_<volume>_<issue>
    back issues    <site>/issue/browser            (all issues, one HTML page)

One TOC page yields every article of that issue (typically 20-23 rows, cover
and contents included).  Each article row links to
``<site>/article/abstract/<article_id>``; the abstract page carries a
``<site>/article/pdf/<article_id>`` link that returns the PDF without login.

The script downloads each PDF into ``data/inbox/<sha16>/original.pdf`` plus a
``meta.json``, and records the article page URL in ``data_items`` under the
journal's source_id with ``state='downloaded'``.  Articles already present in
``data_items`` are skipped, requests are spaced >= 2 s apart and use a normal
browser User-Agent.

Usage (from apps/api):

    uv run python ../../scripts/download_journal_pdf.py \
        --journal jfc --listing https://www.china-fishery.com/scxuebao/issue/browser \
        --since-year 2020 --limit 20

    uv run python ../../scripts/download_journal_pdf.py \
        --journal pfs \
        --listing https://journal.yykxjz.cn/yykxjz/article/issue/2026_47_5 \
        --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html as html_lib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

INBOX = ROOT / "data" / "inbox"

# Publisher / licence facts are per journal and verified on the policy pages:
#   水产学报        https://www.china-fishery.com/scxuebao/site/menus/20230407133217001
#   渔业科学进展    https://journal.yykxjz.cn/yykxjz/site/menus/20241113101745001
JOURNALS: dict[str, dict[str, str]] = {
    "jfc": {
        "source_id": "jfc-oa",
        "publisher": "水产学报",
        "license": "CC BY-NC-ND 4.0",
        "license_url": "https://www.china-fishery.com/scxuebao/site/menus/20230407133217001",
    },
    "pfs": {
        "source_id": "pfs-oa",
        "publisher": "渔业科学进展",
        "license": "CC BY-NC-ND 4.0",
        "license_url": "https://journal.yykxjz.cn/yykxjz/site/menus/20241113101745001",
    },
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MIN_INTERVAL = 2.0  # seconds between any two HTTP requests
ISSUE_RE = re.compile(r"([\w.-]+/article/issue/(\d{4})_(\d+)_(\d+))")
ARTICLE_ROW_RE = re.compile(
    r"<div class=\"article_title\">\s*<a href=['\"]([^'\"]*?/article/abstract/(\d+))['\"][^>]*>(.*?)</a>",
    re.S,
)
PDF_HREF_RE = re.compile(r"['\"]([^'\"]*?/article/pdf/\d+)['\"]")
TAG_RE = re.compile(r"<[^>]+>")


def _clean_title(raw: str) -> str:
    value = html_lib.unescape(TAG_RE.sub("", raw))
    return re.sub(r"\s+", " ", value).strip()


def _decode(resp: httpx.Response) -> str:
    for enc in ("utf-8", "gb18030"):
        try:
            return resp.content.decode(enc)
        except UnicodeDecodeError:
            continue
    return resp.content.decode("utf-8", errors="replace")


def _abs(url: str, href: str) -> str:
    """Resolve a site link against the host root (links are root-relative).

    Some abstract pages emit absolute ``http://china-fishery.com/...`` links
    without the ``www.`` host, which does not resolve; normalise them to the
    scheme/host of the page we are already fetching.
    """
    base = urlsplit(url)
    if href.startswith("//"):
        href = f"{base.scheme}:{href}"
    if href.startswith("http"):
        parts = urlsplit(href)
        host = parts.netloc
        if not host.startswith("www.") and base.netloc.startswith("www."):
            host = f"www.{host}"
        query = f"?{parts.query}" if parts.query else ""
        path = re.sub(r"/{2,}", "/", parts.path)
        return f"{base.scheme}://{host}{path}{query}"
    return f"{base.scheme}://{base.netloc}/{href.lstrip('/')}"


class Fetch:
    """httpx client that keeps requests polite (>= MIN_INTERVAL apart)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.last = 0.0
        self.calls = 0

    async def get(self, url: str, **kwargs) -> httpx.Response:
        wait = MIN_INTERVAL - (time.monotonic() - self.last)
        if wait > 0:
            await asyncio.sleep(wait)
        self.last = time.monotonic()
        self.calls += 1
        return await self.client.get(url, **kwargs)


def parse_issues(page: str, base: str, since_year: int) -> list[tuple[str, str]]:
    """Return [(issue_key, url)] newest first from a /issue/browser page."""
    found: dict[str, str] = {}
    for match in ISSUE_RE.finditer(page):
        path, year, vol, issue = match.groups()
        if int(year) < since_year:
            continue
        key = f"{year}_{vol}_{issue}"
        found[key] = _abs(base, path)
    return sorted(
        found.items(),
        key=lambda kv: tuple(int(x) for x in kv[0].split("_")),
        reverse=True,
    )


def parse_articles(page: str, base: str) -> list[dict[str, str]]:
    """Return article rows from one issue TOC, minus cover / contents entries."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in ARTICLE_ROW_RE.finditer(page):
        href, article_id, raw_title = match.groups()
        if article_id in seen:
            continue
        # cover (YYYYII00) and contents (YYYYII000) share the issue prefix and
        # end in zeros; they are not articles.
        if re.fullmatch(r"\d{4}\d{2}0{2,3}", article_id):
            continue
        title = _clean_title(raw_title)
        if not title or title in {"目录", "目次"} or "封面" in title or "封底" in title:
            continue
        seen.add(article_id)
        rows.append(
            {
                "article_id": article_id,
                "title": title,
                "url": _abs(base, href),
            }
        )
    return rows


async def first_existing(url: str) -> str | None:
    from app.db import SessionLocal

    async with SessionLocal() as db:
        row = (
            await db.execute(
                text("SELECT state FROM data_items WHERE url = :u"), {"u": url}
            )
        ).first()
    return row[0] if row else None


async def record(
    journal: dict[str, str], article: dict[str, str], *, state: str, meta: dict
) -> None:
    from app.db import SessionLocal

    async with SessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO data_items (source_id, url, title, kind, state, license, meta) "
                "VALUES (:s, :u, :t, 'pdf', :st, :lic, CAST(:m AS jsonb)) "
                "ON CONFLICT (url) DO NOTHING"
            ),
            {
                "s": journal["source_id"],
                "u": article["url"],
                "t": article["title"],
                "st": state,
                "lic": journal["license"],
                "m": json.dumps(meta, ensure_ascii=False),
            },
        )
        await db.commit()


async def mark_downloaded(article_url: str, sha: str, size: int, meta: dict) -> None:
    from app.db import SessionLocal

    async with SessionLocal() as db:
        await db.execute(
            text(
                "UPDATE data_items SET state='downloaded', sha256=:s, bytes=:b, "
                "final_url=:f, fetched_at=now(), attempts=attempts+1, "
                "meta = meta || CAST(:m AS jsonb), updated_at=now() "
                "WHERE url=:u"
            ),
            {
                "s": sha,
                "b": size,
                "f": meta["final_url"],
                "m": json.dumps(
                    {"sha256": sha, "bytes": size, "pdf_url": meta["pdf_url"],
                     "pages": meta.get("pages"), "license": meta["license"],
                     "license_url": meta["license_url"],
                     "publisher": meta["publisher"], "journal": meta["journal"]},
                    ensure_ascii=False,
                ),
                "u": article_url,
            },
        )
        await db.commit()


async def mark_failed(article_url: str, error: str) -> None:
    from app.db import SessionLocal

    async with SessionLocal() as db:
        await db.execute(
            text(
                "UPDATE data_items SET state='failed', attempts=attempts+1, "
                "last_error=:e, updated_at=now() WHERE url=:u"
            ),
            {"e": error[:200], "u": article_url},
        )
        await db.commit()


def pdf_pages(data: bytes) -> int | None:
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError:
            return None
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001
        return None


async def main(args: argparse.Namespace) -> int:
    journal = JOURNALS[args.journal]
    from app.db import init_db

    await init_db()

    if args.limit <= 0:
        print("limit must be positive", file=sys.stderr)
        return 2

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    }
    inbox = Path(args.inbox)
    stats = {"issues": 0, "enumerated": 0, "skipped_existing": 0, "downloaded": 0,
             "failed": 0, "bytes": 0}

    async with httpx.AsyncClient(
        timeout=180, follow_redirects=True, headers=headers
    ) as client:
        fetch = Fetch(client)

        # 1. Expand issue listings (browser page or explicit TOC URLs).
        issues: list[tuple[str, str]] = []
        for listing in args.listing:
            resp = await fetch.get(listing)
            page = _decode(resp)
            if "/issue/browser" in listing:
                expanded = parse_issues(page, listing, args.since_year)
                print(f"listing {listing} -> {len(expanded)} issues since {args.since_year}")
                issues.extend(expanded)
            else:
                hit = ISSUE_RE.search(listing)
                key = "_".join(hit.groups()[1:]) if hit else listing
                issues.append((key, listing))
                print(f"listing {listing} (single issue)")
            stats["issues"] = len(issues)

        if args.dry_run:
            for key, url in issues[: args.issues]:
                resp = await fetch.get(url)
                rows = parse_articles(_decode(resp), url)
                print(f"{key} {url} articles={len(rows)} e.g. {rows[0]['title'][:40] if rows else '-'}")
                stats["enumerated"] += len(rows)
            print(json.dumps(stats, ensure_ascii=False))
            return 0

        # 2. Walk issues newest-first until the limit is reached.
        done = 0
        for key, issue_url in issues:
            resp = await fetch.get(issue_url)
            articles = parse_articles(_decode(resp), issue_url)
            print(f"issue {key}: {len(articles)} articles")
            stats["enumerated"] += len(articles)

            for article in articles:
                if done >= args.limit:
                    break
                existing = await first_existing(article["url"])
                if existing is not None and not (
                    args.retry_failed and existing == "failed"
                ):
                    stats["skipped_existing"] += 1
                    print(f"skip existing ({existing}) {article['url']}")
                    continue

                # abstract page -> title confirmation + PDF link
                try:
                    art_resp = await fetch.get(article["url"])
                    art_html = _decode(art_resp)
                except Exception as exc:  # noqa: BLE001
                    stats["failed"] += 1
                    print(f"ERR abstract {article['url']} {type(exc).__name__}")
                    continue

                title_match = re.search(r"<title>(.*?)</title>", art_html, re.S)
                if title_match:
                    alt = _clean_title(title_match.group(1))
                    if alt:
                        article["title"] = alt
                elif not article["title"]:
                    article["title"] = article["article_id"]

                pdf_match = PDF_HREF_RE.search(art_html)
                if not pdf_match:
                    stats["failed"] += 1
                    print(f"ERR no pdf link {article['url']}")
                    await record(journal, article, state="failed",
                                 meta={"reason": "no_pdf_link"})
                    await mark_failed(article["url"], "no_pdf_link")
                    continue

                pdf_url = _abs(article["url"], pdf_match.group(1))

                await record(journal, article, state="discovered",
                             meta={"pdf_url": pdf_url, "journal": journal["publisher"]})

                try:
                    pdf_resp = await fetch.get(pdf_url)
                    data = pdf_resp.content
                    status = pdf_resp.status_code
                    final_url = str(pdf_resp.url)
                except Exception as exc:  # noqa: BLE001
                    stats["failed"] += 1
                    print(f"ERR pdf {pdf_url} {type(exc).__name__}")
                    await mark_failed(article["url"], f"{type(exc).__name__}")
                    continue

                if status != 200 or not data[:1024].lstrip().startswith(b"%PDF"):
                    stats["failed"] += 1
                    print(f"ERR not a pdf {status} {pdf_url} head={data[:16]!r}")
                    await mark_failed(article["url"], f"http_{status}_not_pdf")
                    continue

                sha = hashlib.sha256(data).hexdigest()
                slug = sha[:16]
                target = inbox / slug
                target.mkdir(parents=True, exist_ok=True)
                (target / "original.pdf").write_bytes(data)
                pages = pdf_pages(data)
                meta = {
                    "url": article["url"],
                    "final_url": final_url,
                    "title": article["title"],
                    "format": "pdf",
                    "sha256": sha,
                    "bytes": len(data),
                    "license": journal["license"],
                    "license_url": journal["license_url"],
                    "publisher": journal["publisher"],
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "authority": "academic_journal",
                    "language": "zh",
                    "journal": journal["publisher"],
                    "source_id": journal["source_id"],
                    "article_id": article["article_id"],
                    "pdf_url": pdf_url,
                    "http_status": status,
                    "pages": pages,
                }
                (target / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                await mark_downloaded(article["url"], sha, len(data), meta)
                done += 1
                stats["downloaded"] += 1
                stats["bytes"] += len(data)
                print(
                    f"{done}/{args.limit} ok {slug} pages={pages} "
                    f"{len(data)/1e6:.2f}MB {article['title'][:40]}"
                )

            if done >= args.limit:
                break

    print(json.dumps({**stats, "requests": fetch.calls}, ensure_ascii=False))
    return 0 if stats["downloaded"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", choices=sorted(JOURNALS), required=True)
    parser.add_argument("--listing", action="append", required=True,
                        help="issue TOC URL or /issue/browser URL (repeatable)")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--issues", type=int, default=3,
                        help="number of issues to enumerate with --dry-run")
    parser.add_argument("--since-year", type=int, default=2020)
    parser.add_argument("--inbox", default=str(INBOX))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true",
                        help="re-attempt articles recorded as failed (never re-downloads)")
    raise SystemExit(asyncio.run(main(parser.parse_args())))