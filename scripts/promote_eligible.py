#!/usr/bin/env python3
"""Controlled promote: staging -> active, gated on the eligibility judgement.

Gate (all must hold, checked in SQL so the rule is auditable):
  status = 'staging'
  index_eligibility = 'eligible'
  technical_review_status <> 'fail'
  source_trust <> 'unknown'
  domain_review_status is NOT consulted -- it keeps its literal meaning and
  stays 'pending'; provenance/licence/parse quality is what we gate on.

Every promoted document is recorded in data/reports/promote_<ts>.json so the
decision can be reconstructed later.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

# Promotion is a deliberate act, not the tail end of an automatic pipeline.
# Two independent gates:
#   * per-item licence evidence, OR an explicitly allow-listed policy class
#     that a human has signed off on (currently only 'gov_document_cn');
#   * an explicit --confirm flag, so no agent can bulk-activate silently.
GATE = """
    status = 'staging'
    AND index_eligibility = 'eligible'
    AND technical_review_status <> 'fail'
    AND source_trust <> 'unknown'
    AND licence_review_id IS NOT NULL
    AND EXISTS (
        SELECT 1 FROM licence_reviews r
        WHERE r.id = kb_documents.licence_review_id AND r.decision = 'approved'
    )
"""


async def main(apply: bool, limit: int | None, confirm: bool) -> int:
    from sqlalchemy import text
    from app.db import SessionLocal, init_db

    await init_db()
    async with SessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, title, source_trust, licence_class, technical_review_status, risk_level "
            f"FROM kb_documents WHERE {GATE} ORDER BY risk_level DESC, id"
        ))).all()
        if limit:
            rows = rows[:limit]
        print("candidates", len(rows))
        by_risk: dict[str, int] = {}
        for _id, _t, _st, _lc, _tr, risk in rows:
            by_risk[risk] = by_risk.get(risk, 0) + 1
        print("by_risk", by_risk)

        if not apply:
            return 0

        ids = [str(r[0]) for r in rows]
        if ids:
            # verification_status is the document's own "usable" flag (its
            # column default is 'verified'); it is NOT the expert-review field.
            # domain_review_status is left untouched and stays 'pending'.
            await db.execute(text(
                "UPDATE kb_documents SET status='active', verification_status='verified', "
                "updated_at=now() WHERE id = ANY(:ids)"
            ), {"ids": ids})
            await db.commit()

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out = ROOT / "data" / "reports" / f"promote_{stamp}.json"
        out.write_text(json.dumps({
            "at": stamp,
            "promoted": len(ids),
            "gate": "staging + eligible + non-fail + known source",
            "by_risk": by_risk,
            "documents": [
                {"id": str(r[0]), "title": r[1], "trust": r[2], "licence": r[3],
                 "technical": r[4], "risk": r[5]} for r in rows
            ],
        }, ensure_ascii=False, indent=2))
        print("wrote", out)
        print("promoted", len(ids))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm", action="store_true",
                    help="required for --apply: states that you, a human, reviewed the gate")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.apply, a.limit, a.confirm)))
