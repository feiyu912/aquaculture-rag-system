#!/usr/bin/env python3
"""Stage 1: validity checks + rule-based aquaculture filtering.

Inputs  (data/hf_qa/raw/...): Mxode parquet (927,864 rows), AQUA jsonl (20,000).
Outputs (data/hf_qa/processed/):
  mxode_aqua_rules.parquet     rule-positive aquaculture candidates (CN)
  mxode_border_rules.parquet   species-hit but no context (calibration stratum B)
  aqua_test_all.parquet        AQUA-Test with validity flags (EN)
  calibration_sample.jsonl     stratified LLM-labelling sample (seeded)
  stats_rules.json             stage statistics

Rule verdicts are preliminary: precision is measured later against the
LLM-labelled sample and reported with its n — never presented as exact.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lexicon import (  # noqa: E402
    AQUA_TERMS,
    EXCLUDE_TERMS,
    SPECIES_FLAT,
    STRONG_TERMS,
    TOPIC_TERMS,
)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "hf_qa" / "raw"
OUT = ROOT / "data" / "hf_qa" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

MXODE_REPO = "Mxode/Chinese-QA-Agriculture_Forestry_Animal_Husbandry_Fishery"
MXODE_REV = "d56cf92733cab91615669c7febf8d7f8b86c54b2"
AQUA_REPO = "KurmaAI/AQUA-Test-Dataset"
AQUA_REV = "101ceaa599c9c3c4f7786e39ae0874e4d86cb781"

SEED = 20261021
SAMPLE_POS, SAMPLE_BORDER, SAMPLE_NEG, SAMPLE_AQUA_EN = 800, 400, 400, 200


def alternation(terms: list[str]) -> re.Pattern:
    ordered = sorted({t for t in terms if t}, key=len, reverse=True)
    return re.compile("|".join(re.escape(t) for t in ordered), re.IGNORECASE)


RE_SPECIES = alternation(SPECIES_FLAT)
RE_AQUA = alternation(AQUA_TERMS)
RE_STRONG = alternation(STRONG_TERMS)
RE_EXCLUDE = alternation(EXCLUDE_TERMS)
RE_TOPICS = {k: alternation(v) for k, v in TOPIC_TERMS.items()}


def findall(pat: re.Pattern, text: str) -> list[str]:
    seen: list[str] = []
    for m in pat.finditer(text):
        t = m.group(0)
        if t not in seen:
            seen.append(t)
    return seen


def classify(prompt: str, response: str) -> dict:
    text = f"{prompt}\n{response}"
    sp = findall(RE_SPECIES, text)
    aqua = findall(RE_AQUA, text)
    strong = findall(RE_STRONG, text)
    excluded = findall(RE_EXCLUDE, text)
    topics = {k: findall(p, text) for k, p in RE_TOPICS.items()}
    active = sorted(k for k, v in topics.items() if v)
    species_hit = bool(sp)
    is_aqua = (species_hit and (bool(aqua) or bool(strong))) or (
        bool(strong) and not excluded
    ) or (species_hit and not excluded and bool(active))
    return {
        "is_aqua": is_aqua,
        "species_hits": sp,
        "aqua_hits": aqua,
        "strong_hits": strong,
        "exclude_hits": excluded,
        "topics": active,
    }


def valid(q: str, a: str) -> str | None:
    """Return rejection reason or None when the pair is usable."""
    q = (q or "").strip()
    a = (a or "").strip()
    if len(q) < 6:
        return "question_too_short"
    if len(a) < 10:
        return "answer_too_short"
    if q == a:
        return "answer_equals_question"
    return None


def main() -> None:
    stats: dict = {"seed": SEED}

    # ---- Mxode (CN) -------------------------------------------------------
    src = RAW / MXODE_REPO.replace("/", "__") / MXODE_REV[:12] / "Chinese-QA-AFAF-train-v2.parquet"
    pf = pq.ParquetFile(src)
    total = invalid = 0
    invalid_reasons: dict[str, int] = {}
    aqua_rows: list[dict] = []
    border_rows: list[dict] = []
    neg_sample_pool: list[dict] = []
    neg_total = 0

    for gi in range(pf.metadata.num_row_groups):
        tbl = pf.read_row_group(gi, columns=["id", "prompt", "response"])
        for rid, q, a in zip(tbl.column("id").to_pylist(), tbl.column("prompt").to_pylist(), tbl.column("response").to_pylist()):
            total += 1
            reason = valid(q, a)
            if reason:
                invalid += 1
                invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
                continue
            c = classify(q, a)
            row = {
                "dataset_id": MXODE_REPO,
                "revision": MXODE_REV,
                "original_id": rid,
                "question": q.strip(),
                "answer": a.strip(),
                "is_aqua": c["is_aqua"],
                "species_hits": c["species_hits"],
                "aqua_hits": c["aqua_hits"][:8],
                "strong_hits": c["strong_hits"],
                "exclude_hits": c["exclude_hits"],
                "topics": c["topics"],
            }
            if c["is_aqua"]:
                aqua_rows.append(row)
            elif c["species_hits"]:
                border_rows.append(row)
            else:
                neg_total += 1
                if len(neg_sample_pool) < 20000:
                    neg_sample_pool.append(
                        {
                            "dataset_id": MXODE_REPO,
                            "original_id": rid,
                            "question": q.strip(),
                            "answer": a.strip(),
                            "species_hits": [],
                            "topics": [],
                        }
                    )
        if (gi + 1) % 200 == 0:
            print(f"row_group {gi + 1}/{pf.metadata.num_row_groups} total={total} aqua={len(aqua_rows)}", flush=True)

    stats["mxode"] = {
        "total": total,
        "invalid": invalid,
        "invalid_reasons": invalid_reasons,
        "valid": total - invalid,
        "rule_positive": len(aqua_rows),
        "rule_border": len(border_rows),
        "rule_negative": neg_total,
    }

    pq.write_table(pa.Table.from_pylist(aqua_rows), OUT / "mxode_aqua_rules.parquet")
    pq.write_table(pa.Table.from_pylist(border_rows), OUT / "mxode_border_rules.parquet")

    # ---- AQUA-Test (EN) ---------------------------------------------------
    src = RAW / AQUA_REPO.replace("/", "__") / AQUA_REV[:12] / "AQUA-test.jsonl"
    aqua_en_rows: list[dict] = []
    en_invalid = 0
    with open(src, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            q, a = r.get("question", ""), r.get("response", "")
            reason = valid(q, a)
            if reason:
                en_invalid += 1
                invalid_reasons[f"en_{reason}"] = invalid_reasons.get(f"en_{reason}", 0) + 1
                continue
            aqua_en_rows.append(
                {
                    "dataset_id": AQUA_REPO,
                    "revision": AQUA_REV,
                    "original_id": f"line-{i}",
                    "question": q.strip(),
                    "answer": a.strip(),
                }
            )
    stats["aqua_test"] = {
        "total": 20000,
        "invalid": en_invalid,
        "valid": len(aqua_en_rows),
    }
    pq.write_table(pa.Table.from_pylist(aqua_en_rows), OUT / "aqua_test_all.parquet")

    # ---- stratified calibration sample ------------------------------------
    rng = random.Random(SEED)
    sample = []
    for stratum, pool, k in (
        ("rule_positive", aqua_rows, SAMPLE_POS),
        ("rule_border", border_rows, SAMPLE_BORDER),
        ("rule_negative", neg_sample_pool, SAMPLE_NEG),
    ):
        for r in rng.sample(pool, min(k, len(pool))):
            sample.append(
                {
                    "stratum": stratum,
                    "dataset_id": r["dataset_id"],
                    "original_id": r["original_id"],
                    "question": r["question"],
                    "answer": r["answer"][:1500],
                    "species_hits": r["species_hits"],
                    "topics": r["topics"],
                }
            )
    for r in rng.sample(aqua_en_rows, min(SAMPLE_AQUA_EN, len(aqua_en_rows))):
        sample.append(
            {
                "stratum": "en_quality",
                "dataset_id": r["dataset_id"],
                "original_id": r["original_id"],
                "question": r["question"],
                "answer": r["answer"][:1500],
            }
        )
    with open(OUT / "calibration_sample.jsonl", "w", encoding="utf-8") as f:
        for r in sample:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats["calibration_sample"] = {
        "rule_positive": min(SAMPLE_POS, len(aqua_rows)),
        "rule_border": min(SAMPLE_BORDER, len(border_rows)),
        "rule_negative": min(SAMPLE_NEG, len(neg_sample_pool)),
        "en_quality": min(SAMPLE_AQUA_EN, len(aqua_en_rows)),
    }
    stats["invalid_reasons"] = invalid_reasons

    with open(OUT / "stats_rules.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
