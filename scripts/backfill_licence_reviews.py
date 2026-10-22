#!/usr/bin/env python3
"""Close the licence-review gap with evidence that is labelled by kind.

The active corpus contains documents whose licence basis was never recorded
(`licence_review_id IS NULL`). This script links them to review records, but it
must not flatten different strengths of evidence into one "approved" label:

  item_licence_field   the publisher's own per-item rights statement
  repository_terms     a repository-wide agreement (weaker; may restrict reuse)
  policy_inference     a statutory reading by the author (a judgement, not law)

Every record carries `evidence_kind` plus the verbatim quote it rests on, so a
reader can see whether "approved" means "the licence says CC BY" or "we read
§5 as covering official forecasts".

It never touches status, technical_review_status or domain_review_status.
Run without --apply for a dry run; --apply --confirm writes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

RIGHTS_FILE = ROOT / "data" / "reports" / "worldfish_rights.json"
EULA_URL = "https://digitalarchive.worldfishcenter.org/info/end-user-agreement"
COPYRIGHT_LAW_URL = "https://www.gov.cn/xinwen/2020-11/11/content_5561144.htm"
STANDARD_REVIEW_SCOPE = "cn_public_standard_platform"

EULA_QUOTE = (
    "The Content ... are provided on the Site \u201cAS IS\u201d for your information and "
    "personal use only. ... you are granted a limited license to access and use the Site "
    "and to download or print a copy of any portion of the Content ... solely for your "
    "personal, non-commercial use. ... you agree not to: Systematically retrieve data or "
    "other content from the Site to create or compile, directly or indirectly, a "
    "collection, compilation, database, or directory without written permission from us."
)

S5_QUOTE = (
    "《中华人民共和国著作权法》第五条：本法不适用于：（一）法律、法规，国家机关的决议、"
    "决定、命令和其他具有立法、行政、司法性质的文件，及其官方正式译文；"
    "（二）单纯事实消息；（三）历法、通用数表、通用表格和公式。"
)

ART24_QUOTE = (
    "《中华人民共和国著作权法》第二十四条（六）：为学校课堂教学或者科学研究，翻译、改编、"
    "汇编、播放或者少量复制已经发表的作品，供教学或者科研人员使用，但不得出版发行。"
)

INTERNAL_ONLY = (
    "仅限内部非商业检索使用；不公开再分发；保留发布机构、标题与原文链接；不用于训练对外发布的模型。"
)

CC_CONDITIONS = (
    "按逐条 dc:rights 声明的 CC 条款使用；仅限内部非商业检索；保留出处；"
    "NC/ND 条款按其原文执行。"
)

# scope -> record definition. Decisions are the author's, made on the stated
# basis; the quote is what a reader checks the decision against.
RECORDS: dict[str, dict] = {
    "worldfish-item-cc-by": {
        "basis": "item_licence_field",
        "decision": "approved",
        "evidence_kind": "item_licence_field",
        "evidence_quote": "逐条 OAI-PMH dc:rights 字段为 CC BY 系列许可（例如 “CC BY 4.0”）。",
        "conditions": CC_CONDITIONS,
    },
    "worldfish-item-cc-by-nc": {
        "basis": "item_licence_field",
        "decision": "approved",
        "evidence_kind": "item_licence_field",
        "evidence_quote": "逐条 OAI-PMH dc:rights 字段为 CC BY-NC 系列许可（例如 “CC-BY-NC-4.0”）。",
        "conditions": CC_CONDITIONS,
    },
    "worldfish-item-cc-by-nd": {
        "basis": "item_licence_field",
        "decision": "approved",
        "evidence_kind": "item_licence_field",
        "evidence_quote": "逐条 OAI-PMH dc:rights 字段为 CC BY-ND 系列许可。",
        "conditions": CC_CONDITIONS,
    },
    "worldfish-item-cc-by-nc-nd": {
        "basis": "item_licence_field",
        "decision": "approved",
        "evidence_kind": "item_licence_field",
        "evidence_quote": "逐条 OAI-PMH dc:rights 字段为 CC BY-NC-ND 4.0。",
        "conditions": CC_CONDITIONS,
    },
    "worldfish-item-cc-by-sa": {
        "basis": "item_licence_field",
        "decision": "approved",
        "evidence_kind": "item_licence_field",
        "evidence_quote": "逐条 OAI-PMH dc:rights 字段为 CC BY-SA 系列许可。",
        "conditions": CC_CONDITIONS,
    },
    "worldfish-item-public-domain": {
        "basis": "item_licence_field",
        "decision": "approved",
        "evidence_kind": "item_licence_field",
        "evidence_quote": "逐条 OAI-PMH dc:rights 字段为 “No known copyright restrictions”。",
        "conditions": INTERNAL_ONLY,
    },
    "worldfish-item-other-licence": {
        "basis": "item_licence_field",
        "decision": "approved",
        "evidence_kind": "item_licence_field",
        "evidence_quote": "逐条 OAI-PMH dc:rights 字段为 GPL-3.0-or-later。",
        "conditions": INTERNAL_ONLY,
    },
    "worldfish-item-copyrighted-nc-only": {
        "basis": "item_licence_field",
        "decision": "approved",
        "evidence_kind": "item_licence_field",
        "evidence_quote": "逐条 OAI-PMH dc:rights 字段为 “Copyrighted; Non-commercial use only”。",
        "conditions": INTERNAL_ONLY,
    },
    "worldfish-item-all-rights-reserved": {
        "basis": "item_licence_field",
        "decision": "rejected",
        "evidence_kind": "item_licence_field",
        "evidence_quote": "逐条 OAI-PMH dc:rights 字段为 “Copyrighted; all rights reserved”。",
        "conditions": None,
    },
    "worldfish-repository": {
        "basis": "repository_terms",
        "decision": "unverified",
        "evidence_kind": "repository_terms",
        "evidence_url": EULA_URL,
        "evidence_quote": EULA_QUOTE,
        "conditions": INTERNAL_ONLY,
    },
    "cn-gov-s5-forecast": {
        "supersedes": "cn-gov-s5",
        "basis": "statute_s5_inference",
        "decision": "approved",
        "evidence_kind": "policy_inference",
        "evidence_url": COPYRIGHT_LAW_URL,
        "evidence_quote": S5_QUOTE,
        "conditions": INTERNAL_ONLY + " 该依据为法律推断，不是法律意见或已确认的法律事实。",
    },
    "cn-gov-news-research-exemption": {
        "basis": "research_exemption_cn_art24_6",
        "decision": "approved",
        "evidence_kind": "policy_inference",
        "evidence_url": COPYRIGHT_LAW_URL,
        "evidence_quote": ART24_QUOTE,
        "conditions": INTERNAL_ONLY + " 该依据为法律推断，不是法律意见或已确认的法律事实。",
    },
}

# Existing records keep their decisions; only the evidence kind is filled in so
# the whole audit table can be read the same way.
EXISTING_KIND = {
    "oa_journal_cc_by_nc_nd": "publisher_policy",
    "local_gov_tech_articles": "policy_inference",
    "cn_public_standard_platform": "platform_public_access",
    "worldfish-repository": "repository_terms",
    "cn-gov-s5": "policy_inference",
}


def normalize_rights(raw: str) -> str:
    """Map a publisher rights string onto a licence family."""
    text = (raw or "").strip()
    upper = re.sub(r"[\s_]+", " ", text.upper())
    if "NO KNOWN COPYRIGHT" in upper or "PUBLIC DOMAIN" in upper:
        return "public-domain"
    if "NON-COMMERCIAL USE ONLY" in upper:
        return "copyrighted-nc-only"
    if "ALL RIGHT" in upper or "ALL RIGHTS" in upper or "COPYRIGHTED" in upper:
        return "all-rights-reserved"
    if "GPL" in upper or "CC0" in upper or "MIT" in upper:
        return "other-licence"
    if "CC" in upper and "BY" in upper:
        if "NC" in upper and "ND" in upper:
            return "cc-by-nc-nd"
        if "NC" in upper:
            return "cc-by-nc"
        if "ND" in upper:
            return "cc-by-nd"
        if "SA" in upper:
            return "cc-by-sa"
        return "cc-by"
    if not upper:
        return "no-rights-field"
    return "unknown"


def review_key_for_rights(kind: str) -> str:
    if kind in {"no-rights-field", "unknown"}:
        return "worldfish-repository"
    if kind == "all-rights-reserved":
        return "worldfish-item-all-rights-reserved"
    return f"worldfish-item-{kind}"


async def run(apply: bool, confirm: bool, downgrade_rejected: bool) -> int:
    from sqlalchemy import text

    from app.db import SessionLocal, init_db

    if apply and not confirm:
        print("--apply requires --confirm (a human reviewed the basis)", file=sys.stderr)
        return 2

    rights: dict[str, list[str]] = {}
    if RIGHTS_FILE.exists():
        for row in json.loads(RIGHTS_FILE.read_text(encoding="utf-8")):
            rights[row["document_id"]] = row.get("rights") or []
    else:
        print(f"warning: {RIGHTS_FILE} missing; WorldFish stays unlinked", file=sys.stderr)

    await init_db()
    async with SessionLocal() as db:
        existing = {
            r.scope: r
            for r in (
                await db.execute(
                    text(
                        "SELECT id, scope, decision, evidence_kind FROM licence_reviews ORDER BY created_at"
                    )
                )
            ).all()
        }
        docs = [
            dict(r._mapping)
            for r in (
                await db.execute(
                    text(
                        """
                        SELECT id, title, source_org, source_trust, licence_class,
                               index_eligibility, licence_review_id, doc_genre, source_url,
                               metadata->>'source_id' AS source_id
                        FROM kb_documents
                        WHERE status = 'active'
                          AND licence_review_id IS NULL
                        ORDER BY id
                        """
                    )
                )
            ).all()
        ]

        def pick_review(doc: dict) -> tuple[str | None, str | None]:
            """Return (scope, short evidence code) for one document.

            licence_evidence is varchar(24), so the code is deliberately terse;
            the family-specific detail lives in the linked licence_reviews row.
            """
            org = doc["source_org"]
            if org == "WorldFish":
                found = rights.get(str(doc["id"]))
                if found is None:
                    return None, None
                kind = normalize_rights(found[0]) if found else "no-rights-field"
                scope = review_key_for_rights(kind)
                code = {
                    "cc-by": "item:cc-by",
                    "cc-by-nc": "item:cc-by-nc",
                    "cc-by-nd": "item:cc-by-nd",
                    "cc-by-sa": "item:cc-by-sa",
                    "cc-by-nc-nd": "item:cc-by-nc-nd",
                    "public-domain": "item:public_domain",
                    "other-licence": "item:other_licence",
                    "copyrighted-nc-only": "item:copyrighted_nc",
                    "all-rights-reserved": "item:arr",
                }.get(kind, "repo:terms")
                return scope, code
            if doc["source_trust"] == "official_national":
                scope = (
                    "cn-gov-s5-forecast"
                    if doc["doc_genre"] == "normative_document"
                    else "cn-gov-news-research-exemption"
                )
                return scope, (
                    "policy:s5" if scope == "cn-gov-s5-forecast" else "policy:art24_6"
                )
            is_standard = "dbba.sacinfo.org.cn" in (doc["source_url"] or "") or (
                (doc["source_org"] or "").endswith("市场监督管理局")
                and (doc["title"] or "").upper().startswith("DB")
            )
            if not doc["source_trust"] and is_standard:
                return STANDARD_REVIEW_SCOPE, "platform:public_access"
            return None, None

        assignments: list[tuple[str, str, dict]] = []
        unassigned: list[dict] = []
        for doc in docs:
            scope, payload = pick_review(doc)
            if scope is None:
                unassigned.append(doc)
            else:
                assignments.append((str(doc["id"]), scope, payload or ""))

        by_scope = Counter(scope for _, scope, _ in assignments)
        print(f"active docs without licence review: {len(docs)}")
        print(f"assignable: {len(assignments)}  unassigned: {len(unassigned)}")
        for scope, n in by_scope.most_common():
            print(f"  {scope:<42} {n}")

        # Check the WorldFish harvest covers every WorldFish doc.
        wf = [d for d in docs if d["source_org"] == "WorldFish"]
        wf_missing = [d for d in wf if str(d["id"]) not in rights]
        print(f"worldfish docs: {len(wf)}  without harvested rights: {len(wf_missing)}")

        if not apply:
            return 0

        now = datetime.now(UTC)
        scope_ids: dict[str, str] = {}
        for scope, spec in RECORDS.items():
            if scope not in by_scope:
                continue
            if scope in existing:
                scope_ids[scope] = str(existing[scope].id)
                await db.execute(
                    text(
                        "UPDATE licence_reviews SET evidence_kind=:kind, conditions=:cond, "
                        "evidence_quote=coalesce(nullif(evidence_quote,''), :quote) "
                        "WHERE id=:id"
                    ),
                    {
                        "id": scope_ids[scope],
                        "kind": spec["evidence_kind"],
                        "cond": spec.get("conditions"),
                        "quote": spec.get("evidence_quote"),
                    },
                )
                continue
            supersedes = existing.get(spec.get("supersedes", ""))
            row = (
                await db.execute(
                    text(
                        """
                        INSERT INTO licence_reviews
                            (scope, basis, decision, evidence_url, evidence_quote,
                             reviewer, decided_at, evidence_kind, conditions, supersedes_id)
                        VALUES (:scope, :basis, :decision, :url, :quote,
                                'user_decision_plan_a', :now, :kind, :cond, :supersedes)
                        RETURNING id
                        """
                    ),
                    {
                        "scope": scope,
                        "basis": spec["basis"],
                        "decision": spec["decision"],
                        "url": spec.get("evidence_url"),
                        "quote": spec.get("evidence_quote"),
                        "now": now,
                        "kind": spec["evidence_kind"],
                        "cond": spec.get("conditions"),
                        "supersedes": str(supersedes.id) if supersedes else None,
                    },
                )
            ).scalar_one()
            scope_ids[scope] = str(row)

        # Scopes that already have a record (standards, journals, local tech)
        # are reused as-is; only their evidence kind is labelled below.
        for scope in by_scope:
            if scope not in scope_ids and scope in existing:
                scope_ids[scope] = str(existing[scope].id)

        # Existing decisions get their evidence kind labelled too.
        for scope, kind in EXISTING_KIND.items():
            if scope in existing:
                await db.execute(
                    text("UPDATE licence_reviews SET evidence_kind=:kind WHERE scope=:scope"),
                    {"kind": kind, "scope": scope},
                )

        for doc_id, scope, payload in assignments:
            review_id = scope_ids[scope]
            await db.execute(
                text(
                    "UPDATE kb_documents SET licence_review_id=:rid, "
                    "licence_evidence=:ev, updated_at=now() WHERE id=:id"
                ),
                {"rid": review_id, "ev": payload, "id": doc_id},
            )
            if scope.startswith("worldfish-item-cc") or scope == "worldfish-item-public-domain":
                await db.execute(
                    text(
                        "UPDATE kb_documents SET licence_class='cc_explicit' "
                        "WHERE id=:id AND licence_class='repository_open_access'"
                    ),
                    {"id": doc_id},
                )
            if scope == STANDARD_REVIEW_SCOPE:
                await db.execute(
                    text(
                        "UPDATE kb_documents SET source_trust=coalesce(source_trust,'official_standard'), "
                        "index_eligibility=coalesce(index_eligibility,'eligible'), "
                        "licence_class=coalesce(licence_class,'unclear') WHERE id=:id"
                    ),
                    {"id": doc_id},
                )

        # Rejected per-item licences are a factual correction, not a deletion:
        # the document keeps its status but stops counting as publishable.
        if downgrade_rejected:
            rejected = [
                doc_id for doc_id, scope, _ in assignments
                if scope == "worldfish-item-all-rights-reserved"
            ]
            if rejected:
                await db.execute(
                    text(
                        "UPDATE kb_documents SET index_eligibility='pending_licence', "
                        "updated_at=now() WHERE id = ANY(:ids)"
                    ),
                    {"ids": rejected},
                )

        await db.commit()

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        gate = await db.execute(
            text(
                """
                SELECT count(*) FROM kb_documents d
                WHERE d.status='active' AND d.index_eligibility='eligible'
                  AND d.technical_review_status<>'fail'
                  AND d.source_trust IS NOT NULL AND d.source_trust<>'unknown'
                  AND EXISTS (SELECT 1 FROM licence_reviews r
                              WHERE r.id=d.licence_review_id AND r.decision='approved')
                """
            )
        )
        publishable = gate.scalar_one()
        by_kind = (
            await db.execute(
                text(
                    """
                    SELECT r.evidence_kind, r.decision, count(*) FROM kb_documents d
                    JOIN licence_reviews r ON r.id=d.licence_review_id
                    WHERE d.status='active' GROUP BY 1,2 ORDER BY 3 DESC
                    """
                )
            )
        ).all()
        report = {
            "at": stamp,
            "assignments": len(assignments),
            "unassigned": [
                {"id": str(d["id"]), "title": d["title"], "org": d["source_org"]}
                for d in unassigned
            ],
            "by_scope": dict(by_scope),
            "worldfish_without_rights": len(wf_missing),
            "publishable_after": publishable,
            "by_evidence_kind": [list(map(str, row)) for row in by_kind],
            "downgraded_rejected": bool(downgrade_rejected),
        }
        out = ROOT / "data" / "reports" / f"licence_backfill_{stamp}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"publishable after: {publishable}")
        print(f"wrote {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument(
        "--downgrade-rejected",
        action="store_true",
        help="set index_eligibility=pending_licence for all-rights-reserved items",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.apply, args.confirm, args.downgrade_rejected))


if __name__ == "__main__":
    raise SystemExit(main())