#!/usr/bin/env python3
"""Four independent judgements, deliberately kept apart:

  source_trust       who published it (whitelist; does NOT imply permission)
  licence_class      what the rights allow (repository OA, CN government
                     document, explicit CC, or unclear)
  technical quality  technical_review_status (separate column, untouched)
  domain_review      a named human expert; stays 'pending' unless a human acts

index_eligibility is the AND of trust + licence + not-failed. 'pending_licence'
is a real outcome, not a synonym for 'probably fine'.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

TRUST = {
    "nftec": "official_national",
    "agri": "official_national",
    "moa": "official_national",
    "cafs": "research_institute",
    "ffrc": "research_institute",
    "jfc": "research_institute",     # 水产学报 (CC BY-NC-ND)
    "pfs": "research_institute",     # 渔业科学进展 (CC BY-NC-ND)
    "std-": "official_standard",     # 行业/地方标准平台
    # Provincial / municipal agriculture departments. Trust is clear; the
    # licence is NOT -- these are drafted articles, not 行政文件, so they stay
    # pending_licence rather than riding on the gov_document_cn inference.
    "sh-": "official_local",
    "gd-": "official_local",
    "hb-": "official_local",
    "hn-": "official_local",
    "js-": "official_local",
    "zj-": "official_local",
    "worldfish": "international_org",
    "wf-": "international_org",
    "naca": "international_org",
}

# 著作权法 §5: laws, regulations and administrative documents are not protected
# by copyright. Provincial disease forecasts / official notices are such
# documents; institutional articles (FFRC 科研进展, CAFS 品种介绍) are not.
GOV_DOC_SOURCES = ("nftec-ybfk", "nftec-tzgg", "nftec-wudaxingdong", "agri")
OPEN_ACCESS_SOURCES = ("worldfish",)

# Operational advice that needs a *current, citable* authority. Bare units
# (mg/L, ppm) and standard numbers alone are NOT treated as drug risk.
DRUG_RISK = re.compile(
    r"剂量|用药量|给药|泼洒药物|拌饵投喂|休药期|禁用药物|停用药物|"
    r"孔雀石绿|硝基呋喃|氯霉素|磺胺|喹诺酮|氟苯尼考|恩诺沙星|抗生素治疗"
)
DISEASE_RISK = re.compile(r"病害|防治|治疗|病原|症状|感染|暴发|防控|诊断")


def trust_of(sid: str) -> str:
    for prefix, tier in TRUST.items():
        if (sid or "").lower().startswith(prefix):
            return tier
    return "unknown"


def licence_of(sid: str, lic_meta: str | None) -> str:
    sid = (sid or "").lower()
    lic = (lic_meta or "").lower()
    # Normalise before matching: publishers write "CC BY-NC-ND 4.0", "CC-BY-4.0",
    # "Creative Commons Attribution" -- a raw substring test misses all but one.
    norm = re.sub(r"[^a-z0-9]+", "-", lic)
    if "cc-by" in norm or "creative-commons" in norm:
        return "cc_explicit"
    if any(sid.startswith(p) for p in OPEN_ACCESS_SOURCES) and "open" in lic:
        return "repository_open_access"
    if any(sid.startswith(p) for p in GOV_DOC_SOURCES):
        return "gov_document_cn"
    return "unclear"


async def main(apply: bool) -> int:
    from sqlalchemy import text
    from app.db import SessionLocal, init_db

    await init_db()
    async with SessionLocal() as db:
        rows = (await db.execute(text(
            # LATERAL ... LIMIT 1: several data_items rows can share one
            # document (sync links by hash), which used to double the tally.
            "SELECT d.id, coalesce(i.source_id, d.metadata->>'source_id') sid, "
            "d.technical_review_status, coalesce(d.metadata->>'license', i.lic) lic, "
            "(SELECT r.decision FROM licence_reviews r WHERE r.id = d.licence_review_id) review_decision "
            "FROM kb_documents d LEFT JOIN LATERAL ("
            "  SELECT source_id, coalesce(meta->>'license', metadata->>'license') lic "
            "  FROM data_items WHERE document_id = d.id LIMIT 1) i ON true "
            "WHERE d.status='staging'"
        ))).all()

        tally: dict[tuple[str, str], int] = {}
        for doc_id, sid, tech, lic, review in rows:
            trust = trust_of(sid or "")
            lclass = licence_of(sid or "", lic)
            sample = (await db.execute(text(
                "SELECT string_agg(substring(content from 1 for 300), ' ') FROM ("
                "  SELECT content FROM kb_chunks WHERE document_version_id = "
                "  (SELECT current_version_id FROM kb_documents WHERE id = :d) "
                "  ORDER BY ordinal LIMIT 30) t"
            ), {"d": doc_id})).scalar() or ""
            risk = "high" if DRUG_RISK.search(sample) else (
                "medium" if DISEASE_RISK.search(sample) else "low")

            if trust == "unknown" or tech == "fail":
                elig = "ineligible"
            elif lclass == "unclear" and review == "approved":
                # An explicit, evidence-backed licence review outranks the
                # coarse class: a human/agent recorded the basis and the quote.
                elig = "eligible"
            elif lclass == "unclear":
                elig = "pending_licence"
            else:
                elig = "eligible"
            tally[(elig, risk)] = tally.get((elig, risk), 0) + 1
            if apply:
                await db.execute(text(
                    "UPDATE kb_documents SET source_trust=:t, licence_class=:l, "
                    "index_eligibility=:e, risk_level=:r WHERE id=:d"
                ), {"t": trust, "l": lclass, "e": elig, "r": risk, "d": doc_id})
        if apply:
            await db.commit()
        for k in sorted(tally):
            print(k[0], k[1], tally[k])
        print("rows", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--apply" in sys.argv)))
