#!/usr/bin/env python3
"""Stage 1b: v2 tiered filtering with the calibrated lexicon.

Rescans the raw parquet once (single lexicon version) and assigns tiers:
  tier1  species + aquaculture context        (labelled precision 85.8%)
  tier2  strong aquaculture terms only        (73.6%)
  tier3  no species, >= 2 distinct context terms, no exclusion hit
         (recall recovery pool; precision measured on a fresh 300-row sample)
  dropped: species+topics_only (39.1%), species+strong (0%), everything else

Outputs: mxode_tiers.parquet, tier3_sample.jsonl, stats_v2.json
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lexicon import classify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "hf_qa" / "raw"
OUT = ROOT / "data" / "hf_qa" / "processed"
MXODE_REPO = "Mxode/Chinese-QA-Agriculture_Forestry_Animal_Husbandry_Fishery"
MXODE_REV = "d56cf92733cab91615669c7febf8d7f8b86c54b2"
SEED = 20261021


def tier_of(c: dict) -> str:
    sp = bool(c["species_hits"])
    aq = c["aqua_context_hits"]
    st = c["strong_hits"]
    ex = c["exclude_hits"]
    tp = c["topics"]
    if sp and aq:
        return "tier1"
    if st and not sp:
        return "tier2"
    if sp and st:
        return "tier2"
    if not sp and len(set(aq)) >= 2 and not ex:
        return "tier3"
    if sp and tp:
        return "dropped_topics_only"
    return "negative"


def main() -> None:
    src = RAW / MXODE_REPO.replace("/", "__") / MXODE_REV[:12] / "Chinese-QA-AFAF-train-v2.parquet"
    pf = pq.ParquetFile(src)
    tiers: dict[str, list[dict]] = {"tier1": [], "tier2": [], "tier3": []}
    counts: Counter = Counter()
    for gi in range(pf.metadata.num_row_groups):
        tbl = pf.read_row_group(gi, columns=["id", "prompt", "response"])
        for rid, q, a in zip(tbl.column("id").to_pylist(), tbl.column("prompt").to_pylist(), tbl.column("response").to_pylist()):
            q, a = (q or "").strip(), (a or "").strip()
            if len(q) < 6 or len(a) < 10 or q == a:
                counts["invalid"] += 1
                continue
            c = classify(q + "\n" + a)
            t = tier_of(c)
            counts[t] += 1
            if t.startswith("tier"):
                tiers[t].append(
                    {
                        "dataset_id": MXODE_REPO,
                        "revision": MXODE_REV,
                        "original_id": rid,
                        "question": q,
                        "answer": a,
                        "tier": t,
                        "species_hits": c["species_hits"],
                        "aqua_hits": c["aqua_context_hits"][:10],
                        "strong_hits": c["strong_hits"],
                        "exclude_hits": c["exclude_hits"],
                        "topics": c["topics"],
                    }
                )
        if (gi + 1) % 200 == 0:
            print(f"row_group {gi+1}/{pf.metadata.num_row_groups} tier1={counts['tier1']} tier2={counts['tier2']} tier3={counts['tier3']}", flush=True)

    all_rows = tiers["tier1"] + tiers["tier2"] + tiers["tier3"]
    pq.write_table(pa.Table.from_pylist(all_rows), OUT / "mxode_tiers.parquet")

    rng = random.Random(SEED)
    sample = rng.sample(tiers["tier3"], min(300, len(tiers["tier3"])))
    with open(OUT / "tier3_sample.jsonl", "w", encoding="utf-8") as f:
        for r in sample:
            f.write(
                json.dumps(
                    {
                        "stratum": "tier3",
                        "dataset_id": r["dataset_id"],
                        "original_id": r["original_id"],
                        "question": r["question"],
                        "answer": r["answer"][:1500],
                        "species_hits": [],
                        "topics": r["topics"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    stats = {"counts": dict(counts), "tier3_sample": len(sample), "seed": SEED}
    with open(OUT / "stats_v2.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()