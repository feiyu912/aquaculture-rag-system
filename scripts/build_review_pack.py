#!/usr/bin/env python3
"""Build an evidence pack for per-document review cards.

The point is to give a CS reviewer (not a aquaculture domain expert) enough
*verifiable* material to judge a document's provenance and parse quality, and to
see exactly which clauses need a domain expert.

For every staging document it collects:

* provenance (registry fields, URL, publisher, date, license, doc type);
* structure (headings, page coverage, chunk counts, table leftovers);
* parse anomalies (no chunks, missing pages, duplicated text, mojibake,
  over/under-sized chunks, cross-page joins, empty section paths);
* *verbatim* key clauses containing numbers + units, with page and section, so
  the reviewer never has to trust an LLM paraphrase;
* risk flags for drugs / banned substances / disease treatment / applicability.

Output: ``data/reports/review_pack.json`` plus a short digest on stdout.

Usage:
    uv run python ../../scripts/build_review_pack.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import KbChunk, KbDocument  # noqa: E402

UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s?(?:mg/L|mg/l|mg·L|g/L|g|kg|μg/L|ug/L|%|℃|°C|pH|d\b|天|cm|mm|m\b|亩|尾|万尾|L\b|mL|h\b|min|次|遍|片|粒)"
)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
RISK_TERMS = {
    "drug": ["恩诺沙星", "氟苯尼考", "抗生素", "磺胺", "土霉素", "孔雀石绿", "氯霉素", "硝基呋喃", "停药期", "休药期"],
    "banned": ["禁用", "违禁", "不得使用", "停止使用"],
    "disease": ["治疗", "病害", "防治", "病原", "感染", "发病"],
    "dose": ["用量", "剂量", "浓度", "mg/L", "泼洒", "拌饵"],
}
MOJIBAKE = ("锟斤拷", "Ã", "â€", "\ufffd")
TABLE_HINT = re.compile(r"^\s*\|.*\|\s*$")


def snippet(text: str, limit: int = 260) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned[:limit]


def english_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for ch in letters if ch.isascii())
    return latin / len(letters)


def scan_chunks(chunks: list[KbChunk]) -> dict:
    if not chunks:
        return {"count": 0, "anomalies": ["no_chunks"]}
    lengths = [len(c.content or "") for c in chunks]
    pages = [c.page_from for c in chunks if c.page_from]
    dup_counter = Counter(re.sub(r"\s+", "", (c.content or ""))[:200] for c in chunks)
    duplicates = sum(count - 1 for count in dup_counter.values() if count > 1)

    anomalies: list[str] = []
    if any(not c.page_from for c in chunks):
        anomalies.append("chunk_without_page")
    if min(lengths) < 40:
        anomalies.append("chunk_under_40_chars")
    if max(lengths) > 3000:
        anomalies.append("chunk_over_3000_chars")
    if duplicates:
        anomalies.append(f"duplicate_chunk_text x{duplicates}")
    cross = sum(1 for c in chunks if c.page_from and c.page_to and c.page_from != c.page_to)
    if chunks and cross / len(chunks) > 0.5:
        anomalies.append(f"cross_page_dominant x{round(100 * cross / len(chunks))}%")
    if sum(1 for c in chunks if not (c.heading_path or [])) > len(chunks) * 0.3:
        anomalies.append("mostly_missing_section_path")
    NAV_PREFIXES = ("欢迎您！来到全国水产技术推广总站", "无障碍 农芯慧答", "相关附件：", "主办单位：")
    if any(any(p in (c.content or "")[:120] for p in NAV_PREFIXES) for c in chunks):
        anomalies.append("navigation_boilerplate")
    table_heavy = sum(
        1 for c in chunks if "|" in (c.content or "")
    )
    if table_heavy > len(chunks) * 0.5:
        anomalies.append(f"table_heavy x{table_heavy}")
    heading_pollution = sum(
        1 for c in chunks for h in (c.heading_path or []) if len(h) > 40
    )
    if heading_pollution > len(chunks) * 0.05:
        anomalies.append(f"heading_pollution x{heading_pollution}")
    pages = [c.page_from for c in chunks if c.page_from]
    if pages and max(pages) >= 10 and len(chunks) / max(pages) < 3:
        anomalies.append("low_chunk_density")

    joined = " ".join((c.content or "")[:400] for c in chunks[:60])
    for bad in MOJIBAKE:
        if bad in joined:
            anomalies.append(f"mojibake:{bad!r}")
            break
    if sum(1 for c in chunks if any(TABLE_HINT.match(line) for line in (c.content or "").splitlines())) > 0:
        anomalies.append("has_markdown_tables")

    lower_start = sum(1 for c in chunks if (c.content or "")[:1].islower())

    return {
        "count": len(chunks),
        "lower_start_pct": round(100.0 * lower_start / len(chunks), 1),
        "avg_len": round(sum(lengths) / len(lengths)),
        "min_len": min(lengths),
        "max_len": max(lengths),
        "pages": len(set(pages)) if pages else 0,
        "page_min": min(pages) if pages else None,
        "page_max": max(pages) if pages else None,
        "anomalies": anomalies,
    }


def key_clauses(chunks: list[KbChunk], limit: int = 8) -> list[dict]:
    """Verbatim sentences that carry a number with a unit."""
    picked: list[dict] = []
    seen: set[str] = set()
    for chunk in chunks:
        text = re.sub(r"\s+", " ", chunk.content or "").strip()
        if not text:
            continue
        for sentence in re.split(r"(?<=[。；;.!?])\s*", text):
            if len(sentence) < 8 or not UNIT_RE.search(sentence):
                continue
            key = sentence[:40]
            if key in seen:
                continue
            seen.add(key)
            risk = [name for name, terms in RISK_TERMS.items() if any(t in sentence for t in terms)]
            picked.append(
                {
                    "quote": sentence[:400],
                    "page": chunk.page_from,
                    "section": " > ".join(chunk.heading_path or [])[:120],
                    "risk": risk,
                }
            )
            if len(picked) >= limit:
                return picked
    return picked


def risk_summary(chunks: list[KbChunk]) -> dict:
    blob = " ".join((c.content or "") for c in chunks)
    counts = {name: sum(blob.count(term) for term in terms) for name, terms in RISK_TERMS.items()}
    return {name: count for name, count in counts.items() if count}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(ROOT / "data" / "reports" / "review_pack.json"))
    parser.add_argument("--per-doc-facts", type=int, default=8)
    parser.add_argument("--digest", action="store_true", help="print a short digest")
    args = parser.parse_args()

    await init_db()
    docs: list[dict] = []
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(KbDocument).where(KbDocument.status == "staging").order_by(KbDocument.title)
            )
        ).scalars().all()

        for doc in rows:
            chunks = (
                await db.execute(
                    select(KbChunk)
                    .where(
                        KbChunk.document_version_id == doc.current_version_id,
                        KbChunk.chunk_role == "child",
                    )
                    .order_by(KbChunk.ordinal)
                )
            ).scalars().all()
            meta = doc.doc_metadata or {}
            stats = scan_chunks(list(chunks))
            heading_counter: Counter[str] = Counter()
            for chunk in chunks:
                path = chunk.heading_path or []
                if path:
                    heading_counter[path[0]] += 1
            first_text = next((c.content for c in chunks if (c.content or "").strip()), "")
            docs.append(
                {
                    "id": str(doc.id),
                    "title": doc.title,
                    "source_id": meta.get("source_id"),
                    "source_type": doc.source_type,
                    "authority_level": doc.authority_level,
                    "document_status": meta.get("document_status"),
                    "verification_status": doc.verification_status,
                    "publisher": doc.source_org,
                    "source_url": doc.source_url,
                    "publish_year": doc.publish_year,
                    "publish_date": meta.get("publish_date"),
                    "license": meta.get("license"),
                    "doc_type": meta.get("doc_type"),
                    "region": meta.get("region"),
                    "species": doc.species or [],
                    "declared_topics": meta.get("topics") or [],
                    "fetched_at": meta.get("fetched_at"),
                    "sha256": (meta.get("sha256") or "")[:16],
                    "language": "en" if english_ratio(first_text) > 0.6 else "zh",
                    "structure": stats,
                    "headings": [name for name, _ in heading_counter.most_common(10)],
                    "first_paragraph": snippet(first_text, 320),
                    "key_clauses": key_clauses(list(chunks), args.per_doc_facts),
                    "risk_terms": risk_summary(list(chunks)),
                }
            )

    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"documents": docs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"documents={len(docs)} -> {path}")

    if args.digest:
        for item in docs:
            s = item["structure"]
            print(f"\n### {item['title'][:56]}  [{item['source_type']}/{item['authority_level']}]")
            print(f"  pub={item['publisher']} date={item['publish_date'] or item['publish_year']} lic={item['license']}")
            print(f"  chunks={s.get('count')} pages={s.get('page_min')}..{s.get('page_max')} lang={item['language']}")
            print(f"  anomalies={s.get('anomalies')}")
            print(f"  headings={item['headings'][:5]}")
            print(f"  first={item['first_paragraph'][:150]}")
            for fact in item["key_clauses"][:3]:
                print(f"    · p{fact['page']} {fact['quote'][:110]}")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))