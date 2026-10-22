#!/usr/bin/env python3
"""Stage 4: build the formal eval set with document-grounded references.

For each candidate question:
  1. run the *document* retrieval path (read-only, include_faq=False);
  2. ask the LLM whether the top evidence excerpts can answer it and, only if
     yes, write the reference answer FROM those excerpts;
  3. keep the question only when answerable=yes with >=1 supporting excerpt.

HF answers are never used as truth; they are stored as a diagnostic field only.
Isolation: candidates are checked against existing eval resources and the FAQ
snapshot; the QA-memory exclusion happens later in build_qa_memory.py.

Robustness: results stream to *.partial.jsonl / *.failed.jsonl, questions are
processed in chunks with a per-item timeout, and a rerun resumes from the
existing ledgers — a hung LLM call can no longer lose finished work.

Usage: uv run python build_eval_set.py --probe 20
       uv run python build_eval_set.py --cn 200 --en 50
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "hf_qa" / "processed"
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.ingestion.embedder import get_embedder  # noqa: E402
from app.retrieval.bm25 import BM25SparseEncoder  # noqa: E402
from app.retrieval.service import retrieve  # noqa: E402

SEED = 20261021
CHUNK = 160
ITEM_TIMEOUT = 180
PUNCT = "，。！？；：、（）【】《》“”‘’…—·,.!?;:()[]<>\"'`~ "

VERIFY_PROMPT = """你是水产养殖领域的严格审稿人。下面是用户问题和从专业文献库检索到的编号证据。请判断：仅凭这些证据，能否写出回答问题的参考答案？

硬规则：
- 证据与问题主题相近但答非所问（例如问设备寿命、证据讲技术简介）→ answerable=no
- 证据能回答问题的核心部分即可 answerable=yes；参考答案只写证据支持的内容，问题中未被证据覆盖的部分不得编造
- 只有证据与问题核心无关时才判 no/partial

只输出 JSON：{{"answerable": "yes|partial|no", "supported_indices": [1,2], "reference_answer": "仅当 yes 时填写，1-3 句，中文", "reason": "不超过30字"}}

问题：{q}

证据：
{evidence}"""


def normalize(text: str) -> str:
    v = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in v if ch not in PUNCT)


def trigrams(text: str) -> set[str]:
    v = normalize(text)
    return {v[i : i + 3] for i in range(len(v) - 2)} if len(v) >= 3 else ({v} if v else set())


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def load_llm():
    env = {}
    for line in open(ROOT / "apps" / "api" / ".env", encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    from openai import AsyncOpenAI

    return AsyncOpenAI(base_url=env["OPENAI_BASE_URL"], api_key=env["OPENAI_API_KEY"]), env["OPENAI_MODEL"]


def existing_eval_trigrams() -> list[set[str]]:
    tri = []
    for name, field in (("real_questions_v1.jsonl", "question"), ("sample_questions.jsonl", "question")):
        p = ROOT / "eval" / name
        if not p.exists():
            continue
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line:
                tri.append(trigrams(json.loads(line)[field]))
    p = ROOT / "eval" / "planner_probes_v1.json"
    if p.exists():
        data = json.load(open(p, encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("probes", [])
        for r in items:
            q = r.get("question") or r.get("query") or ""
            if q:
                tri.append(trigrams(q))
    return tri


def faq_trigrams() -> list[set[str]]:
    import csv

    p = ROOT / "data" / "hf_qa" / "external" / "faq_snapshot_20261021.csv"
    return [trigrams(r["question"]) for r in csv.DictReader(open(p, encoding="utf-8"))]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cn", type=int, default=200)
    ap.add_argument("--en", type=int, default=50)
    ap.add_argument("--probe", type=int, default=0, help="only test N per language, write nothing")
    ap.add_argument("--out", default=str(ROOT / "data" / "hf_qa" / "eval" / "eval_set_v1.jsonl"))
    args = ap.parse_args()

    rng = random.Random(SEED)
    cn = [json.loads(l) for l in open(PROC / "eval_candidates_cn.jsonl", encoding="utf-8")]
    en = [json.loads(l) for l in open(PROC / "eval_candidates_en.jsonl", encoding="utf-8")]
    for pool in (cn, en):
        rng.shuffle(pool)

    excl = existing_eval_trigrams() + faq_trigrams()

    def isolated(q: str) -> bool:
        tq = trigrams(q)
        return not any(jaccard(tq, t) >= 0.8 for t in excl)

    client, model = load_llm()
    # One retrieval pass per question: the targeted cascade only inflates build
    # time and does not change which evidence exists.
    settings.enable_targeted_retrieval = False
    emb = get_embedder(settings.embedding_model, settings.qdrant_vector_size, settings.embedding_device,
                       settings.embedding_use_fp16, settings.embedding_batch_size, settings.embedding_max_length)
    bm25 = BM25SparseEncoder(k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len)
    sem = asyncio.Semaphore(20)
    io_sem = asyncio.Semaphore(8)
    stats_lock = asyncio.Lock()
    stats = {
        lang: {"tried": 0, "kept_all": 0, "no_evidence": 0, "no": 0, "partial": 0, "parse_error": 0, "timeout": 0}
        for lang in ("cn", "en")
    }

    async def verify(q: str, quotes: list[str]) -> dict:
        evidence = "\n".join(f"[{i}] {t}" for i, t in enumerate(quotes, start=1))
        prompt = VERIFY_PROMPT.format(q=q, evidence=evidence)
        async with sem:
            for attempt in range(2):
                try:
                    resp = await client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": prompt}],
                        temperature=0.0, max_tokens=1000, timeout=90,
                    )
                    text = resp.choices[0].message.content or ""
                    if not text.strip():
                        text = str(getattr(resp.choices[0].message, "reasoning_content", "") or "")
                    start, end = text.find("{"), text.rfind("}")
                    if start >= 0 and end > start:
                        return json.loads(text[start : end + 1])
                    raise ValueError("no json")
                except Exception:  # noqa: BLE001
                    if attempt == 1:
                        return {"answerable": "parse_error"}
                    await asyncio.sleep(2)
        return {"answerable": "parse_error"}

    async def handle_one(r: dict, lang: str) -> dict | None:
        if not isolated(r["question"]):
            return None
        async with stats_lock:
            stats[lang]["tried"] += 1
        async with io_sem:
            async with SessionLocal() as db:
                res = await retrieve(db, r["question"], emb, bm25, mode="hybrid", include_faq=False)
        ev = [e for e in res.evidence if e.source_type == "document"][:3]
        if not ev:
            async with stats_lock:
                stats[lang]["no_evidence"] += 1
            return None
        evidence_texts = [f"《{e.title}》{e.content[:450]}" for e in ev]
        verdict = await verify(r["question"], evidence_texts)
        label = verdict.get("answerable")
        if label != "yes" or not verdict.get("reference_answer"):
            async with stats_lock:
                stats[lang][label if label in ("no", "partial", "parse_error") else "no"] += 1
            return None
        idx = [i for i in verdict.get("supported_indices", []) if isinstance(i, int) and 1 <= i <= len(ev)]
        if not idx:
            async with stats_lock:
                stats[lang]["no"] += 1
            return None
        gold = [
            {
                "document_id": str(ev[i - 1].document_id),
                "version_id": str(ev[i - 1].version_id),
                "chunk_id": str(ev[i - 1].parent_chunk_id),
                "title": ev[i - 1].title,
                "page": ev[i - 1].page,
                "quote": ev[i - 1].quote,
                "content_head": ev[i - 1].content[:400],
                "source_url": ev[i - 1].source_url,
                "authority": ev[i - 1].authority,
            }
            for i in idx
        ]
        row = {
            "eval_id": ("cnx-" if lang == "cn" else "enx-")
            + hashlib.sha256((r["dataset_id"] + r["original_id"]).encode()).hexdigest()[:16],
            "question": r["question"],
            "language": lang,
            "topic": (r.get("topics") or ["未分类"])[0] if r.get("topics") else "未分类",
            "species_hits": r.get("species_hits", []),
            "reference_answer": verdict["reference_answer"],
            "gold_evidence": gold,
            "hf_reference_answer_unverified_diagnostic": r.get("reference_answer_unverified", ""),
            "source_dataset": r["dataset_id"],
            "source_revision": r["revision"],
            "source_original_id": r["original_id"],
            "built_at": datetime.now(UTC).isoformat(),
            "retrieval_mode": "hybrid",
        }
        async with stats_lock:
            stats[lang]["kept_all"] += 1
        return row

    if args.probe:
        probe_results = await asyncio.gather(
            *(asyncio.wait_for(handle_one(r, "cn"), timeout=ITEM_TIMEOUT) for r in cn[: args.probe]),
            *(asyncio.wait_for(handle_one(r, "en"), timeout=ITEM_TIMEOUT) for r in en[: args.probe]),
            return_exceptions=True,
        )
        print(json.dumps({"stats": stats, "kept": sum(1 for x in probe_results if isinstance(x, dict) and x)}, indent=2))
        return

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".partial.jsonl")
    failed = out.with_suffix(".failed.jsonl")

    kept_rows: dict[str, list[dict]] = {"cn": [], "en": []}
    done_q: set[str] = set()
    if partial.exists():
        for line in open(partial, encoding="utf-8"):
            row = json.loads(line)
            kept_rows[row["language"]].append(row)
            done_q.add(normalize(row["question"]))
    if failed.exists():
        for line in open(failed, encoding="utf-8"):
            done_q.add(normalize(json.loads(line)["question"]))
    print(f"resume: kept cn={len(kept_rows['cn'])} en={len(kept_rows['en'])} seen={len(done_q)}", flush=True)

    async def run_pool(pool: list[dict], lang: str, quota: int) -> list[dict]:
        kept = kept_rows[lang]
        with open(partial, "a", encoding="utf-8") as pf, open(failed, "a", encoding="utf-8") as ff:
            for start in range(0, len(pool), CHUNK):
                batch = [r for r in pool[start : start + CHUNK] if normalize(r["question"]) not in done_q]
                if not batch:
                    continue
                results = await asyncio.gather(
                    *(asyncio.wait_for(handle_one(r, lang), timeout=ITEM_TIMEOUT) for r in batch),
                    return_exceptions=True,
                )
                for r, res in zip(batch, results):
                    done_q.add(normalize(r["question"]))
                    if isinstance(res, dict) and res is not None:
                        kept.append(res)
                        pf.write(json.dumps(res, ensure_ascii=False) + "\n")
                    elif isinstance(res, BaseException):
                        async with stats_lock:
                            stats[lang]["timeout"] += 1
                        ff.write(json.dumps({"lang": lang, "question": r["question"], "error": type(res).__name__}, ensure_ascii=False) + "\n")
                    else:
                        ff.write(json.dumps({"lang": lang, "question": r["question"]}, ensure_ascii=False) + "\n")
                pf.flush()
                ff.flush()
                print(f"{lang}: scanned={min(start + CHUNK, len(pool))} kept={len(kept)}", flush=True)
                if len(kept) >= int(quota * 1.2):
                    break
        return kept

    kept_cn = await run_pool(cn, "cn", args.cn)
    kept_en = await run_pool(en, "en", args.en)

    def select(rows: list[dict], quota: int) -> list[dict]:
        by_topic: dict[str, list[dict]] = {}
        for r in rows:
            by_topic.setdefault(r["topic"], []).append(r)
        selected, i = [], 0
        while len(selected) < quota and any(len(v) > i for v in by_topic.values()):
            for topic in sorted(by_topic):
                if i < len(by_topic[topic]) and len(selected) < quota:
                    selected.append(by_topic[topic][i])
            i += 1
        return selected

    selected = select(kept_cn, args.cn) + select(kept_en, args.en)
    with open(out, "w", encoding="utf-8") as f:
        for r in selected:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = {
        "built_at": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "requested": {"cn": args.cn, "en": args.en},
        "kept": {"cn": len(kept_cn), "en": len(kept_en)},
        "selected": {"cn": sum(1 for r in selected if r["language"] == "cn"), "en": sum(1 for r in selected if r["language"] == "en")},
        "stats": stats,
        "isolation_threshold": 0.8,
        "reference_policy": "document evidence only; HF answers stored as diagnostic, never as truth",
    }
    (out.parent / "eval_set_v1.manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())