"""Small deterministic query decomposition for multi-facet questions.

This is deliberately not an LLM planner: every sub-query keeps the original
species/stage context, and the original query is always retrieved unchanged.
"""

from __future__ import annotations

import re

from app.query.ir import QueryIR

SPLIT_RE = re.compile(r"(?:同时|并且|以及|另外|还要|分别|；|;)")
NOISE_RE = re.compile(r"(?:请问|请|帮我|一下|有什么要求|有什么|是什么|怎么样|如何)")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", NOISE_RE.sub("", text)).strip("，。；;、 ")


def decompose_question(question: str, ir: QueryIR | None = None, limit: int = 4) -> list[str]:
    variants: list[str] = []
    if ir is not None and len(ir.water_parameters) > 1:
        prefix = " ".join([*ir.species[:1], *ir.growth_stage[:1]])
        for parameter in ir.water_parameters:
            variants.append(_clean(f"{prefix} {parameter} 要求"))
    parts = SPLIT_RE.split(question)
    if len(parts) > 1:
        for part in parts:
            cleaned = _clean(part)
            if len(cleaned) >= 4:
                variants.append(cleaned)
    deduped: list[str] = []
    for variant in variants:
        if variant and variant != question and variant not in deduped:
            deduped.append(variant)
    return deduped[:limit]
