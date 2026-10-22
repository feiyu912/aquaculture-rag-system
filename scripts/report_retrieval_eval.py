#!/usr/bin/env python3
"""Render a retrieval-eval run into stratified tables and a Markdown report."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ("dense", "bm25", "hybrid", "hybrid_rerank")
METRICS = ("recall@5", "recall@10", "ndcg@10", "mrr@10")


def table(rows: list[dict], key: str, label: str) -> str:
    lines = [f"### 按{label}\n", "| 分组 | n | 模式 | R@5 | R@10 | nDCG@10 | MRR@10 |", "|---|---|---|---|---|---|---|"]
    for value in sorted({row[key] for row in rows}):
        for mode in MODES:
            subset = [row for row in rows if row[key] == value and row["mode"] == mode]
            if not subset:
                continue
            cells = [f"{statistics.mean(r[m] for r in subset):.3f}" for m in METRICS]
            lines.append(f"| {value} | {len(subset)} | {mode} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, default=ROOT / "eval" / "runs" / "retrieval_100_v1")
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "retrieval_eval_100_v1.jsonl")
    args = parser.parse_args()

    cases = {
        row["id"]: row
        for row in (
            json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line
        )
    }
    details = [
        json.loads(line)
        for line in (args.run / "details.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    for row in details:
        row["group"] = cases[row["id"]]["group"]
        row["question_type"] = cases[row["id"]]["question_type"]
    summary = {
        row["mode"]: row
        for row in __import__("csv").DictReader((args.run / "summary.csv").open(encoding="utf-8"))
    }
    manifest = json.loads((args.run / "manifest.json").read_text(encoding="utf-8"))

    lines = [
        "# 检索评测 v1（100 题中文）",
        "",
        f"- 数据集：`{manifest['dataset']}`（sha256 `{manifest['dataset_sha256'][:16]}…`）",
        (
            f"- 集合：`{manifest['collection']}`，embedding `{manifest['embedding_model']}`，"
            f"reranker `{manifest['reranker_model']}`"
        ),
        (
            f"- top_k={manifest['top_k']}，模式：{', '.join(manifest['modes'])}，"
            f"git `{manifest['git_commit'][:8]}`"
        ),
        (
            "- 指标：父块（送入 LLM 的上下文单元）为主，`child_*` 为代表性子块；"
            "拒答按 0 分计入。"
        ),
        "",
        "## 总体",
        "",
        "| 模式 | R@5 | R@10 | nDCG@5 | nDCG@10 | MRR@10 | 平均耗时(ms) | 拒答 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mode in MODES:
        row = summary.get(mode)
        if not row:
            continue
        lines.append(
            f"| {mode} | {row['recall@5']} | {row['recall@10']} | {row['ndcg@5']} | "
            f"{row['ndcg@10']} | {row['mrr@10']} | {row['avg_retrieval_ms']} | {row['refused']} |"
        )
    lines += ["", table(details, "group", "来源"), "", table(details, "question_type", "题型"), ""]
    (args.run / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())