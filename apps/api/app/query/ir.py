"""Typed Query IR v1.

Rules produce a candidate IR; a deterministic validator decides which fields may
become hard filters.  The original question is always preserved.  This module
does not call an LLM, so it is safe to run offline and cannot invent a species,
date, or regulation status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.species import GENERAL_SPECIES, parse_species

Intent = Literal["fact", "complex", "regulation", "calculation"]
Strategy = Literal["simple", "semantic_expansion", "multi_hop", "regulation", "calculation"]

WATER_PARAMETERS = (
    "溶解氧",
    "溶氧",
    "氨氮",
    "亚硝酸盐",
    "酸碱度",
    "pH",
    "水温",
    "盐度",
    "透明度",
    "总碱度",
    "硬度",
    "硫化氢",
    "余氯",
    "COD",
    "BOD",
)
GROWTH_STAGES = (
    "苗种",
    "幼体",
    "仔虾",
    "蜕壳期",
    "成体",
    "越冬",
    "高温期",
    "雨季",
    "养殖前期",
    "养殖中期",
    "养殖后期",
)
DISEASE_TERMS = (
    "病害",
    "疾病",
    "游塘",
    "浮头",
    "摄食下降",
    "黑鳃",
    "烂鳃",
    "白斑",
    "肝胰腺",
    "应激",
    "死亡",
    "感染",
)
REGULATION_TERMS = (
    "规范",
    "标准",
    "法规",
    "农业农村部",
    "禁用",
    "用药",
    "休药期",
    "限量",
    "最新",
    "现行",
    "有效",
    "废止",
    "年份",
)
CALCULATION_TERMS = ("计算", "浓度", "用量", "用量", "换水", "投喂量", "亩", "立方", "ppm", "mg/L")
COMPLEX_MARKERS = ("同时", "并且", "分别", "以及", "有哪些", "如何", "为什么", "影响")
MULTI_HOP_MARKERS = ("先", "然后", "再", "最后")
WATER_ALIASES = (("do", "溶解氧"), ("ph", "酸碱度"), ("溶氧", "溶解氧"))
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*年?")


class QueryIR(BaseModel):
    original_question: str
    normalized_question: str
    intent: Intent = "fact"
    species: list[str] = Field(default_factory=list)
    growth_stage: list[str] = Field(default_factory=list)
    water_parameters: list[str] = Field(default_factory=list)
    diseases: list[str] = Field(default_factory=list)
    requested_year: int | None = None
    requires_current_regulation: bool = False
    strategy: Strategy = "simple"
    species_filter: str | None = None
    category_filter: str | None = None
    unsupported_constraints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source: Literal["rules"] = "rules"
    confidence: float = 0.5


@dataclass(slots=True)
class CompiledConstraints:
    species: str | None
    category: str | None
    unsupported: list[str]
    warnings: list[str]


def _contains_any(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term and term in text]


def _species_mentions(question: str, options: list[str]) -> tuple[list[str], list[str]]:
    """Return exact/longest species hits and suffix aliases.

    A suffix such as "对虾" is only accepted when it identifies exactly one
    known species; this avoids hard-filtering an ambiguous category.
    """
    known = sorted({s for s in options if s and s != GENERAL_SPECIES}, key=len, reverse=True)
    exact = [s for s in known if s in question]
    if exact:
        # Drop a shorter overlap such as "对虾" when "凡纳滨对虾" matched.
        return exact, []
    suffix_hits: set[str] = set()
    for option in known:
        for start in range(1, len(option) - 1):
            if option[start:] in question:
                suffix_hits.add(option)
                break
    aliases = sorted(suffix_hits)
    return [], aliases


def build_query_ir(
    question: str,
    species_options: list[str],
    *,
    explicit_species: str | None = None,
    explicit_category: str | None = None,
) -> QueryIR:
    text = question.strip()
    normalized = re.sub(r"\s+", " ", text)
    exact, aliases = _species_mentions(normalized, species_options)
    species = list(exact or aliases)

    if explicit_species and explicit_species.strip():
        try:
            species = parse_species(explicit_species)
        except ValueError:
            species = []
    species = [s for s in species if s != GENERAL_SPECIES]

    stages = _contains_any(normalized, GROWTH_STAGES)
    parameters = _contains_any(normalized, WATER_PARAMETERS)
    water_alias_used = False
    for alias, canonical in WATER_ALIASES:
        if alias in normalized.lower() and canonical not in parameters:
            parameters.append(canonical)
            water_alias_used = True
    diseases = _contains_any(normalized, DISEASE_TERMS)
    regulation_hits = _contains_any(normalized, REGULATION_TERMS)
    calculation_hits = _contains_any(normalized, CALCULATION_TERMS)
    year_match = YEAR_RE.search(normalized)
    requested_year = int(year_match.group(1)) if year_match else None

    facets = sum(bool(value) for value in (species, stages, parameters, diseases))
    multi_hop = (
        len(parameters) + len(diseases) + len(stages) >= 2
        and any(marker in normalized for marker in MULTI_HOP_MARKERS)
    )
    if regulation_hits:
        intent: Intent = "regulation"
    elif calculation_hits and any(term in normalized for term in ("计算", "用量", "浓度")):
        intent = "calculation"
    elif facets >= 3 or multi_hop or any(marker in normalized for marker in COMPLEX_MARKERS):
        intent = "complex"
    else:
        intent = "fact"

    if intent == "regulation":
        strategy: Strategy = "regulation"
    elif intent == "calculation":
        strategy = "calculation"
    elif multi_hop or (intent == "complex" and facets >= 2):
        strategy = "multi_hop"
    elif aliases or water_alias_used:
        strategy = "semantic_expansion"
    else:
        strategy = "simple"

    warnings: list[str] = []
    unsupported: list[str] = []
    species_filter: str | None = None
    if len(species) == 1:
        species_filter = species[0]
    elif len(species) > 1:
        warnings.append("multiple_species_no_hard_filter")

    if requested_year is not None:
        unsupported.append("published_year")
        warnings.append("year_is_soft_constraint_until_effective_date_metadata_exists")
    if intent == "regulation":
        unsupported.extend(["effective_date", "regulation_status"])
        warnings.append("regulation_metadata_not_available")

    confidence = 0.85 if exact or explicit_species else 0.7 if aliases else 0.45
    return QueryIR(
        original_question=text,
        normalized_question=normalized,
        intent=intent,
        species=species,
        growth_stage=stages,
        water_parameters=parameters,
        diseases=diseases,
        requested_year=requested_year,
        requires_current_regulation=bool(
            regulation_hits
            and (
                requested_year is not None
                or any(t in normalized for t in ("最新", "现行", "有效", "废止"))
            )
        ),
        strategy=strategy,
        species_filter=species_filter,
        category_filter=explicit_category.strip()
        if explicit_category and explicit_category.strip()
        else None,
        unsupported_constraints=sorted(set(unsupported)),
        warnings=warnings,
        confidence=confidence,
    )


def compile_constraints(ir: QueryIR) -> CompiledConstraints:
    """Only fields that the validator trusts become hard filters."""
    return CompiledConstraints(
        species=ir.species_filter,
        category=ir.category_filter,
        unsupported=list(ir.unsupported_constraints),
        warnings=list(ir.warnings),
    )


def route_query(ir: QueryIR) -> Strategy:
    """Deterministic route; LangGraph integration can call the same function."""
    return ir.strategy
