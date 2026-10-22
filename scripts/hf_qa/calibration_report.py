#!/usr/bin/env python3
"""Stage 2b: calibration report from LLM labels.

Produces processed/calibration_report.json with per-stratum rates, Wilson 95%
CIs, and error-mode breakdown.  All numbers are sample estimates with n
attached — never presented as exact corpus facts.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "hf_qa" / "processed"


def wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(rows: list[dict], pred) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    k = sum(1 for r in rows if pred(r))
    lo, hi = wilson(k / n, n)
    return {"n": n, "k": k, "rate": round(k / n, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def main() -> None:
    rows = [json.loads(l) for l in open(OUT / "labeled_sample.jsonl", encoding="utf-8")]
    BAD = ("error", "parse_error")
    UNSURE = ("unsure", "aquaculture|other|unsure")
    for r in rows:
        if r["llm_label"] in UNSURE:
            r["llm_label_norm"] = "unsure"
        elif r["llm_label"] in BAD:
            r["llm_label_norm"] = "error"
        else:
            r["llm_label_norm"] = r["llm_label"]
    errors = [r for r in rows if r["llm_label_norm"] == "error"]
    unsures = [r for r in rows if r["llm_label_norm"] == "unsure"]
    ok = [r for r in rows if r["llm_label_norm"] not in ("error", "unsure")]

    def is_aqua(r: dict) -> bool:
        return r["llm_label"] == "aquaculture"

    by = lambda s: [r for r in ok if r["stratum"] == s]  # noqa: E731

    pos = by("rule_positive")
    border = by("rule_border")
    neg = by("rule_negative")
    en = by("en_quality")

    border_strict = [
        r for r in border if r.get("species_hits") and r.get("topics")
    ]
    border_loose = [r for r in border if not (r.get("species_hits") and r.get("topics"))]

    pos_other_domains = Counter(
        r.get("llm_domain", "?") for r in pos if not is_aqua(r)
    )
    neg_aqua_domains = Counter(
        r.get("llm_domain", "?") for r in neg if is_aqua(r)
    )

    report = {
        "labelling": {
            "total": len(rows),
            "ok": len(ok),
            "unsure": len(unsures),
            "errors": len(errors),
        },
        "rule_positive_precision": rate(pos, is_aqua),
        "border_strict_precision": rate(border_strict, is_aqua),
        "border_loose_precision": rate(border_loose, is_aqua),
        "rule_negative_aqua_rate": rate(neg, is_aqua),
        "en_quality": {
            "n": len(en),
            "good": sum(1 for r in en if r["llm_label"] == "good"),
            "weak": sum(1 for r in en if r["llm_label"] == "weak"),
            "bad": sum(1 for r in en if r["llm_label"] == "bad"),
        },
        "rule_positive_error_modes": dict(pos_other_domains),
        "rule_negative_aqua_domains": dict(neg_aqua_domains),
        "error_rows": [
            {"stratum": r["stratum"], "original_id": r["original_id"], "reason": r["llm_reason"]}
            for r in errors[:20]
        ],
    }
    report["unsure_rows"] = [
        {"stratum": r["stratum"], "question": r["question"][:60], "reason": r["llm_reason"][:60]}
        for r in unsures[:20]
    ]
    with open(OUT / "calibration_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
