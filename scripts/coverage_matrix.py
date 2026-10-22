#!/usr/bin/env python3
"""Coverage matrix: source × theme × document genre, split by licence status.

The matrix reports three numbers per cell so the thesis cannot conflate them:
  eligible  — passes the current publish gate
  isolated  — kept in the database but removed from the index
  total     — all active documents
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

THEMES = [
    ("病害防控", r"病害|疾病|疫病|防控|诊断|治疗|寄生虫|病毒|细菌|水霉|出血病|disease|health|pathogen|parasite|virus|bacterial|infection"),
    ("水质管理", r"水质|溶氧|氨氮|pH|PH|透明度|调控|尾水|排放|底质|water quality|effluent|environment"),
    ("苗种繁育", r"苗种|育苗|繁育|孵化|亲本|催产|淡化|标粗|鱼苗|虾苗|seed|hatchery|broodstock|fingerling|breeding|genetic"),
    ("饲料投喂", r"饲料|投喂|饵料|营养|日粮|投饲|feed|nutrition|diet"),
    ("养殖模式", r"模式|稻虾|稻渔|轮作|混养|循环水|工厂化|网箱|池塘|养殖技术|aquaculture|farming|pond|cage|value chain|system"),
    ("设施工程", r"设施|设备|增氧|工程|智慧化|建设|改造|infrastructure|facility|technology"),
]


def theme_of(title: str) -> str:
    for name, pattern in THEMES:
        if re.search(pattern, title or "", re.IGNORECASE):
            return name
    return "其他"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "runs" / "coverage_v1" / "coverage_matrix_v1")
    args = parser.parse_args()

    from sqlalchemy import text

    from app.db import SessionLocal

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT title, source_trust, source_org, doc_genre, region, index_eligibility, "
                    "technical_review_status FROM kb_documents WHERE status='active'"
                )
            )
        ).all()

    def group(row) -> str:
        if row.source_org == "WorldFish":
            return "WorldFish"
        return {
            "official_standard": "标准",
            "official_local": "地方",
            "official_national": "国家级推广",
            "research_institute": "期刊",
        }.get(row.source_trust, "其他")

    cells: Counter = Counter()
    totals: Counter = Counter()
    for row in rows:
        g = group(row)
        theme = theme_of(row.title)
        totals["all"] += 1
        cells[(g, theme, "total")] += 1
        if row.index_eligibility == "eligible" and row.technical_review_status != "fail":
            cells[(g, theme, "eligible")] += 1
        elif row.index_eligibility in ("pending_licence", "ineligible"):
            cells[(g, theme, "isolated")] += 1

    groups = ["标准", "国家级推广", "地方", "期刊", "WorldFish", "其他"]
    themes = [name for name, _ in THEMES] + ["其他"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.with_suffix(".csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["source_group", "theme", "eligible", "isolated", "total"])
        for g in groups:
            for theme in themes:
                writer.writerow(
                    [g, theme, cells[(g, theme, "eligible")], cells[(g, theme, "isolated")],
                     cells[(g, theme, "total")]]
                )

    lines = [
        "# 覆盖矩阵 v1",
        "",
        "单元格式：可检索 / 已隔离 / 总数。主题按标题规则归类，不是人工标注。",
        "",
        "| 来源 | " + " | ".join(themes) + " | 合计 |",
        "|---" * (len(themes) + 2) + "|",
    ]
    for g in groups:
        cells_row = [
            f"{cells[(g, t, 'eligible')]}/{cells[(g, t, 'isolated')]}/{cells[(g, t, 'total')]}"
            for t in themes
        ]
        total = sum(cells[(g, t, "total")] for t in themes)
        lines.append(f"| {g} | " + " | ".join(cells_row) + f" | {total} |")
    lines.append(
        "| 合计 | "
        + " | ".join(
            f"{sum(cells[(g, t, 'eligible')] for g in groups)}/"
            f"{sum(cells[(g, t, 'isolated')] for g in groups)}/"
            f"{sum(cells[(g, t, 'total')] for g in groups)}"
            for t in themes
        )
        + f" | {totals['all']} |"
    )
    args.out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))