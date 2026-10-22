#!/usr/bin/env python3
"""Stage 3 (v2): dedupe, leakage, tier-aware eval-candidate build.

Acceptance:
  * memory pool  = tier1 + tier2 (tier2 tagged lower confidence)
  * eval pool    = tier1 only (highest labelled precision 85.8%)
  * tier3        = recall-recovery pool, never used for eval
Dedupe keeps the higher tier when the same question appears twice.
Leakage thresholds mirror scripts/check_eval_leakage.py.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "hf_qa" / "processed"
EXT = ROOT / "data" / "hf_qa" / "external"
META_CANDIDATES = ROOT / "data" / "meta" / "qa_candidates.jsonl"

SEED = 20261021
JAC_Q, JAC_A = 0.8, 0.7
NEAR_DUP_IN_SET = 0.85
PUNCT = "，。！？；：、（）【】《》“”‘’…—·,.!?;:()[]<>\"'`~ "


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in value if ch not in PUNCT)


def trigrams(text: str) -> set[str]:
    v = normalize(text)
    if len(v) < 3:
        return {v} if v else set()
    return {v[i : i + 3] for i in range(len(v) - 2)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def inverted(tri_by_id: dict[str, set[str]]) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = defaultdict(list)
    for rid, tris in tri_by_id.items():
        for t in tris:
            idx[t].append(rid)
    return idx


def near_dups(rows: list[dict], threshold: float) -> set[str]:
    tri_by_id = {r["uid"]: trigrams(r["question"]) for r in rows}
    inv = inverted(tri_by_id)
    dropped: set[str] = set()
    for r in rows:
        tris = tri_by_id[r["uid"]]
        overlap: Counter = Counter()
        for t in tris:
            for other in inv[t]:
                if other != r["uid"]:
                    overlap[other] += 1
        for other, cnt in overlap.most_common(5):
            union = len(tris) + len(tri_by_id[other]) - cnt
            if cnt / max(1, union) >= threshold:
                dropped.add(r["uid"])
                break
    return dropped


def main() -> None:
    stats: dict = {"seed": SEED, "thresholds": {"near_dup": NEAR_DUP_IN_SET, "leak_question": JAC_Q, "leak_answer": JAC_A}}
    rng = random.Random(SEED)

    tiers = pq.read_table(OUT / "mxode_tiers.parquet").to_pylist()
    stats["tiers"] = dict(Counter(r["tier"] for r in tiers))

    pool = [r for r in tiers if r["tier"] in ("tier1", "tier2")]
    pool.sort(key=lambda r: (r["tier"] != "tier1", r["original_id"]))
    stats["pool"] = len(pool)

    by_norm: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        by_norm[normalize(r["question"])].append(r)
    deduped, exact_dup_dropped = [], 0
    for group in by_norm.values():
        best = max(group, key=lambda r: (r["tier"] == "tier1", len(r["answer"])))
        deduped.append(best)
        exact_dup_dropped += len(group) - 1
    stats["dedupe_exact"] = {"dropped": exact_dup_dropped, "kept": len(deduped)}

    for i, r in enumerate(deduped):
        r["uid"] = f"cn-{i}"
    dropped = near_dups(deduped, NEAR_DUP_IN_SET)
    kept_cn = [r for r in deduped if r["uid"] not in dropped]
    stats["dedupe_near"] = {"dropped": len(dropped), "kept": len(kept_cn)}
    stats["kept_by_tier"] = dict(Counter(r["tier"] for r in kept_cn))

    faq = list(csv.DictReader(open(EXT / "faq_snapshot_20261021.csv", encoding="utf-8")))
    faq_tri = [(trigrams(f["question"]), trigrams(f["answer"])) for f in faq]
    faq_norm = {normalize(f["question"]) for f in faq}
    leak_faq = 0
    for r in kept_cn:
        if normalize(r["question"]) in faq_norm:
            r["leak"] = "faq_exact"
            leak_faq += 1
            continue
        rq, ra = trigrams(r["question"]), trigrams(r["answer"])
        if any(jaccard(rq, tq) >= JAC_Q or jaccard(ra, ta) >= JAC_A for tq, ta in faq_tri):
            r["leak"] = "faq_near"
            leak_faq += 1
    stats["leak_faq"] = {"flagged": leak_faq}

    meta_norm, meta_tri = {}, {}
    with open(META_CANDIDATES, encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            rid = r.get("cid") or r.get("hf_id") or sha(r["question"])[:16]
            meta_norm[normalize(r["question"])] = rid
            meta_tri[rid] = trigrams(r["question"])
    inv_meta = inverted(meta_tri)
    leak_meta = 0
    for r in kept_cn:
        if normalize(r["question"]) in meta_norm:
            r["leak"] = r.get("leak") or "meta_exact"
            leak_meta += 1
            continue
        tris = trigrams(r["question"])
        overlap: Counter = Counter()
        for t in tris:
            for other in inv_meta[t]:
                overlap[other] += 1
        if any(jaccard(tris, meta_tri[other]) >= JAC_Q for other, _ in overlap.most_common(3)):
            r["leak"] = r.get("leak") or "meta_near"
            leak_meta += 1
    stats["leak_meta_candidates"] = {"flagged": leak_meta}
    clean_cn = [r for r in kept_cn if not r.get("leak")]
    stats["clean_by_tier"] = dict(Counter(r["tier"] for r in clean_cn))

    QWORDS = ("什么", "如何", "怎么", "哪些", "多少", "为什么", "是否", "哪种", "怎样", "为何", "吗")
    tier1 = [r for r in clean_cn if r["tier"] == "tier1"]
    gates: Counter = Counter()
    gated = []
    for r in tier1:
        q, a = r["question"], r["answer"]
        if not (q.endswith("？") or q.endswith("?") or any(w in q for w in QWORDS)):
            gates["not_interrogative"] += 1
            continue
        if not (20 <= len(a) <= 2000):
            gates["answer_len"] += 1
            continue
        if a.startswith(("作为AI", "抱歉", "很抱歉")):
            gates["ai_refusal"] += 1
            continue
        gated.append(r)
    stats["eval_gates"] = dict(gates)

    by_topic: dict[str, list[dict]] = defaultdict(list)
    for r in gated:
        by_topic[r["topics"][0] if r["topics"] else "未分类"].append(r)
    eval_cn = []
    for topic, rows in sorted(by_topic.items()):
        eval_cn.extend(rng.sample(rows, min(300, len(rows))))
    with open(OUT / "eval_candidates_cn.jsonl", "w", encoding="utf-8") as f:
        for r in eval_cn:
            f.write(
                json.dumps(
                    {
                        "eval_id": "cnqa-" + sha(r["dataset_id"] + r["original_id"])[:16],
                        "dataset_id": r["dataset_id"],
                        "revision": r["revision"],
                        "original_id": r["original_id"],
                        "question": r["question"],
                        "reference_answer_unverified": r["answer"],
                        "species_hits": r["species_hits"],
                        "topics": r["topics"],
                        "tier": r["tier"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    stats["eval_cn"] = {
        "tier1_clean": len(tier1),
        "gated": len(gated),
        "selected": len(eval_cn),
        "by_topic": {k: sum(1 for r in eval_cn if (r["topics"][0] if r["topics"] else "未分类") == k) for k in sorted(by_topic)},
    }

    # ---- AQUA-Test (EN) ------------------------------------------------------
    en = pq.read_table(OUT / "aqua_test_all.parquet").to_pylist()
    en_by_norm: dict[str, dict] = {}
    exact_en = 0
    for r in en:
        k = normalize(r["question"])
        if k in en_by_norm:
            exact_en += 1
            continue
        en_by_norm[k] = r
    en_list = list(en_by_norm.values())
    for i, r in enumerate(en_list):
        r["uid"] = f"en-{i}"
    en_dropped = near_dups(en_list, NEAR_DUP_IN_SET)
    en_kept = [r for r in en_list if r["uid"] not in en_dropped]
    en_sample = rng.sample(en_kept, min(500, len(en_kept)))
    with open(OUT / "eval_candidates_en.jsonl", "w", encoding="utf-8") as f:
        for r in en_sample:
            f.write(
                json.dumps(
                    {
                        "eval_id": "enqa-" + sha(r["dataset_id"] + r["original_id"])[:16],
                        "dataset_id": r["dataset_id"],
                        "revision": r["revision"],
                        "original_id": r["original_id"],
                        "question": r["question"],
                        "reference_answer_unverified": r["answer"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    stats["aqua_en"] = {"valid": len(en), "exact_dup": exact_en, "near_dup": len(en_dropped), "kept": len(en_kept), "eval_sample": len(en_sample)}

    with open(OUT / "stats_final.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    for r in kept_cn:
        r.setdefault("leak", "")
    pq.write_table(pa.Table.from_pylist(kept_cn), OUT / "mxode_clean_pool.parquet")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()