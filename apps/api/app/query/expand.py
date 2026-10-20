"""Deterministic query-alias expansion for domain terms.

A regulation often writes ``溶氧量`` while a user asks ``溶解氧``.  Token-level
BM25 will not match those strings even though the Query IR has already identified
the same water parameter.  These variants are conservative string substitutions;
they never invent a new species, parameter, or constraint.
"""

from __future__ import annotations

from app.query.ir import QueryIR

QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "溶解氧": ("溶氧量", "溶氧", "DO"),
    "酸碱度": ("pH值", "pH"),
    "中华绒螯蟹": ("河蟹",),
    "凡纳滨对虾": ("南美白对虾",),
}


def alias_variants(question: str, ir: QueryIR | None, limit: int = 4) -> list[str]:
    if ir is None:
        return []
    variants: list[str] = []
    # Prefer the parameter/facet terms over broad species aliases.
    for parameter in [*ir.water_parameters, *ir.species]:
        aliases = QUERY_ALIASES.get(parameter, ())
        for alias in aliases:
            if alias.lower() in question.lower():
                continue
            if parameter not in question:
                continue
            variant = question.replace(parameter, alias)
            if variant != question and variant not in variants:
                variants.append(variant)
    return variants[:limit]
