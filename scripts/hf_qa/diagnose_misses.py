#!/usr/bin/env python3
"""Attribute eval-build misses: retrieval capability vs coverage mismatch.

For a seeded sample of questions that failed the eval build, run an ORACLE
retrieval that bypasses the production fusion/gates/caps (dense top-60 +
BM25 top-60 over every document chunk, staging included), fetch the parent
texts from PostgreSQL, and let the same verify prompt judge them.

Buckets:
  retrieval   - oracle evidence can answer, and it lives in an ACTIVE document
  inactive    - oracle evidence can answer, but only in non-active (staging) docs
  coverage    - even the oracle cannot answer -> the KB does not cover the topic

Usage: uv run python diagnose_misses.py --cn 60 --en 40
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from qdrant_client import models
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "hf_qa" / "processed"
EVAL = ROOT / "data" / "hf_qa" / "eval" / "eval_set_v1.jsonl"
OUTDIR = ROOT / "data" / "hf_qa" / "diagnostics"
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.ingestion.embedder import get_embedder  # noqa: E402
from app.models import KbChunk, KbDocument, KbDocumentVersion  # noqa: E402
from app.retrieval.bm25 import BM25SparseEncoder  # noqa: E402
from app.retrieval.vector_store import get_client  # noqa: E402
from build_eval_set import VERIFY_PROMPT, load_llm, normalize  # noqa: E402

SEED = 20261021


def doc_filter() -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(key="source_type", match=models.MatchValue(value="document")),
            models.FieldCondition(key="chunk_role", match=models.MatchValue(value="child")),
        ]
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cn", type=int, default=60)
    ap.add_argument("--en", type=int, default=40)
    args = ap.parse_args()

    kept = {normalize(r["question"]) for r in (json.loads(l) for l in open(EVAL, encoding="utf-8"))}
    rng = random.Random(SEED)
    pools = {}
    for lang, file in (("cn", "eval_candidates_cn.jsonl"), ("en", "eval_candidates_en.jsonl")):
        rows = [json.loads(l) for l in open(PROC / file, encoding="utf-8")]
        failures = [r for r in rows if normalize(r["question"]) not in kept]
        rng.shuffle(failures)
        pools[lang] = failures[: getattr(args, lang)]
        print(f"{lang}: failures_pool={len(rows) - sum(1 for r in rows if normalize(r['question']) in kept)} sampled={len(pools[lang])}")

    client, model = load_llm()
    emb = get_embedder(settings.embedding_model, settings.qdrant_vector_size, settings.embedding_device,
                       settings.embedding_use_fp16, settings.embedding_batch_size, settings.embedding_max_length)
    bm25 = BM25SparseEncoder(k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len)
    qdrant = get_client()
    llm_sem = asyncio.Semaphore(8)

    async def oracle_parents(question: str) -> list[dict]:
        dense = (await asyncio.to_thread(emb.embed_query, question))
        dense_hits = qdrant.query_points(
            collection_name=settings.qdrant_collection, query=dense, using="dense",
            query_filter=doc_filter(), limit=60, with_payload=True,
        ).points
        sparse_hits = qdrant.query_points(
            collection_name=settings.qdrant_collection, query=bm25.query_vector(question), using="bm25",
            query_filter=doc_filter(), limit=60, with_payload=True,
        ).points
        best: dict[str, dict] = {}
        for rank, hit in enumerate(dense_hits, start=1):
            parent = str((hit.payload or {}).get("parent_id") or hit.id)
            entry = best.setdefault(parent, {"parent_id": parent, "version_id": (hit.payload or {}).get("document_version_id"), "rank": rank})
            entry["rank"] = min(entry["rank"], rank)
        for rank, hit in enumerate(sparse_hits, start=1):
            parent = str((hit.payload or {}).get("parent_id") or hit.id)
            entry = best.setdefault(parent, {"parent_id": parent, "version_id": (hit.payload or {}).get("document_version_id"), "rank": rank + 100})
            entry["rank"] = min(entry["rank"], rank + 100)
        return sorted(best.values(), key=lambda e: e["rank"])[:10]

    async def run_one(r: dict, lang: str) -> dict:
        parents = await oracle_parents(r["question"])
        pids = [p["parent_id"] for p in parents]
        async with SessionLocal() as db:
            chunks = (await db.execute(select(KbChunk.id, KbChunk.content).where(KbChunk.id.in_(pids)))).all()
            vids = [p["version_id"] for p in parents if p["version_id"]]
            vers = (await db.execute(select(KbDocumentVersion.id, KbDocumentVersion.document_id, KbDocumentVersion.status).where(KbDocumentVersion.id.in_(vids)))).all()
            vmeta = {str(vid): (str(did), st) for vid, did, st in vers}
            dids = list({m[0] for m in vmeta.values()})
            docs = (await db.execute(select(KbDocument.id, KbDocument.title, KbDocument.status).where(KbDocument.id.in_(dids)))).all()
        content_by_id = {str(cid): (content or "") for cid, content in chunks}
        dmeta = {str(did): (title, st) for did, title, st in docs}
        evidence, meta = [], []
        for p in parents:
            text = content_by_id.get(p["parent_id"])
            if not text:
                continue
            did, vst = vmeta.get(str(p["version_id"]), ("", ""))
            title, dst = dmeta.get(did, ("", ""))
            evidence.append(f"《{title or '未知文献'}》{text[:450]}")
            meta.append({"active": dst == "active" and vst == "active", "doc_status": dst, "version_status": vst, "title": title})
            if len(evidence) >= 6:
                break
        if not evidence:
            return {"lang": lang, "question": r["question"], "verdict": "coverage", "reason": "oracle_no_text"}
        prompt = VERIFY_PROMPT.format(q=r["question"], evidence="\n".join(f"[{i}] {t}" for i, t in enumerate(evidence, 1)))
        async with llm_sem:
            try:
                resp = await client.chat.completions.create(
                    model=model, messages=[{"role": "user", "content": prompt}],
                    temperature=0.0, max_tokens=1000, timeout=120,
                )
                text = resp.choices[0].message.content or ""
                if not text.strip():
                    text = str(getattr(resp.choices[0].message, "reasoning_content", "") or "")
                s, e = text.find("{"), text.rfind("}")
                verdict = json.loads(text[s : e + 1]) if s >= 0 and e > s else {"answerable": "parse_error"}
            except Exception as exc:  # noqa: BLE001
                verdict = {"answerable": "parse_error", "reason": str(exc)[:60]}
        answerable = verdict.get("answerable")
        idx = [i for i in verdict.get("supported_indices", []) if isinstance(i, int) and 1 <= i <= len(meta)]
        any_active = any(meta[i - 1]["active"] for i in idx)
        bucket = "coverage"
        if answerable == "yes" and idx:
            bucket = "retrieval" if any_active else "inactive"
        return {
            "lang": lang,
            "question": r["question"],
            "verdict": bucket,
            "answerable": answerable,
            "reason": verdict.get("reason", "")[:80],
            "supporting_titles": [meta[i - 1]["title"][:40] for i in idx],
            "oracle_supporting_active": any_active,
        }

    sem = asyncio.Semaphore(4)

    async def guarded(r, lang):
        async with sem:
            return await run_one(r, lang)

    tasks = [guarded(r, "cn") for r in pools["cn"]] + [guarded(r, "en") for r in pools["en"]]
    results = await asyncio.gather(*tasks)

    summary = defaultdict(Counter)
    for r in results:
        summary[r["lang"]][r["verdict"]] += 1
    report = {
        "built_at": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "sampled": {k: len(v) for k, v in pools.items()},
        "buckets": {lang: dict(c) for lang, c in summary.items()},
        "note": "oracle = dense+bm25 top-60 over all document chunks incl. staging; bypasses fusion, gates and caps",
        "examples": {b: [r for r in results if r["verdict"] == b][:8] for b in ("retrieval", "inactive", "coverage")},
    }
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "attribution_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "examples"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())