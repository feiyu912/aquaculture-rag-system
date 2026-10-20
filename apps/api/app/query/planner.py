"""LLM-assisted natural-language to typed-query-plan conversion.

The LLM proposes a plan; deterministic validators decide what may become a
retrieval filter.  This module never lets an inferred species, year, category,
or regulation status become a hard constraint.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings, settings
from app.query.ir import (
    DISEASE_ALIASES,
    DISEASE_TERMS,
    GROWTH_ALIASES,
    GROWTH_STAGES,
    WATER_ALIASES,
    WATER_PARAMETERS,
    QueryIR,
)
from app.species import GENERAL_SPECIES, SPECIES_ALIASES, canonical_species

Intent = Literal["fact", "complex", "regulation", "calculation"]
Strength = Literal["hard", "soft"]
Source = Literal["explicit", "inferred"]
InheritField = Literal[
    "species", "growth_stage", "water_parameters", "diseases", "year", "category"
]
DEFAULT_INHERITS: list[InheritField] = ["species", "growth_stage"]


class PlannerConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=120)
    source: Source
    strength: Strength


class PlannerSubQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=300)
    facet: str | None = Field(default=None, max_length=40)
    inherits: list[InheritField] = Field(default_factory=lambda: list(DEFAULT_INHERITS))


class PlannerIR(BaseModel):
    """Strict schema returned by the planner model."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent = "fact"
    species: list[str] = Field(default_factory=list)
    growth_stage: list[str] = Field(default_factory=list)
    water_parameters: list[str] = Field(default_factory=list)
    diseases: list[str] = Field(default_factory=list)
    constraints: list[PlannerConstraint] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    rewritten_query: str | None = Field(default=None, max_length=500)
    subquestions: list[PlannerSubQuestion] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class Completer(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 900,
        temperature: float = 0.0,
        response_format: dict | None = None,
    ) -> str: ...


PLANNER_SYSTEM_PROMPT = """你是水产养殖 RAG 系统的查询规划器，不是答题器。
只输出一个 JSON 对象，不要输出 Markdown、解释或代码围栏。
必须严格使用以下字段：
{
  "intent": "fact|complex|regulation|calculation",
  "species": ["标准品种名"],
  "growth_stage": ["阶段"],
  "water_parameters": ["水质指标"],
  "diseases": ["疾病或症状"],
  "constraints": [{"name":"字段名","value":"用户要求","source":"explicit|inferred","strength":"hard|soft"}],
  "assumptions": ["模型推断但未确认的假设"],
  "rewritten_query": "保留原意的检索改写，可为空",
  "subquestions": [{"question":"子问题","facet":"方面","inherits":["species","growth_stage"]}],
  "confidence": 0.0,
  "warnings": ["不确定之处"]
}
规则：
1. 不回答问题，不引入资料中没有的品种、数值、年份或法规状态。
2. 只有用户原问题明确出现的品种、指标、阶段才可标为 explicit；推断项必须标 inferred。
3. 硬约束只用于用户明确、可验证的条件；不确定的条件必须是 soft 或放进 assumptions。
4. 复杂问题拆成 1-4 个可独立检索的子问题；子问题通过 inherits 声明继承原问题的字段，只能是 species/growth_stage/water_parameters/diseases/year/category 的子集；默认 species、growth_stage。
5. 不要编造疾病诊断或用药剂量。输出必须是合法 JSON。"""


def should_use_llm_planner(ir: QueryIR) -> bool:
    """Use the paid planner only where rule IR is likely insufficient.

    A single-facet factual question already has a reliable rule IR.  Spending
    tens of seconds on an LLM there hurts latency without adding constraints.
    """
    facets = sum(
        bool(value) for value in (ir.species, ir.growth_stage, ir.water_parameters, ir.diseases)
    )
    comparison = any(
        marker in ir.original_question
        for marker in ("是否", "差异", "区别", "分别", "对比", "比较", "哪个", "还是")
    )
    return ir.intent in {"complex", "regulation", "calculation"} or facets >= 2 or comparison


def build_planner_messages(
    question: str,
    rule_ir: QueryIR,
    species_options: list[str],
) -> list[dict[str, str]]:
    known = [item for item in species_options if item and item != GENERAL_SPECIES]
    user = {
        "question": question,
        "known_species": known,
        "rule_ir": rule_ir.model_dump(),
    }
    return [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "请解析以下问题并输出 JSON：\n" + json.dumps(user, ensure_ascii=False),
        },
    ]


def _strip_json(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        value = value[start : end + 1]
    return value.strip()


def parse_planner_json(text: str) -> PlannerIR:
    try:
        payload = json.loads(_strip_json(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"planner returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError("planner output must be a JSON object")
    try:
        return PlannerIR.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"planner schema validation failed: {exc}") from exc


def _canonical_terms(raw: list[str], allowed: tuple[str, ...]) -> list[str]:
    aliases = {term.lower(): term for term in allowed}
    aliases.update({"do": "溶解氧", "ph": "酸碱度", "溶氧": "溶解氧"})
    aliases.update({alias.lower(): canonical for alias, canonical in GROWTH_ALIASES})
    aliases.update({alias.lower(): canonical for alias, canonical in DISEASE_ALIASES})
    result: list[str] = []
    for item in raw:
        key = str(item).strip().lower()
        term = aliases.get(key)
        if term and term not in result:
            result.append(term)
    return result


def _species_in_text(text: str, options: list[str]) -> list[str]:
    hits: list[str] = []
    for option in options:
        if not option or option == GENERAL_SPECIES:
            continue
        if option in text or any(
            alias in text for alias, canonical in SPECIES_ALIASES.items() if canonical == option
        ):
            hits.append(option)
    return list(dict.fromkeys(hits))


def _mentioned(term: str, question: str) -> bool:
    if term in question:
        return True
    lowered = question.lower()
    for alias, canonical in WATER_ALIASES:
        if canonical == term and alias in lowered:
            return True
    for alias, canonical in GROWTH_ALIASES:
        if canonical == term and alias in lowered:
            return True
    for alias, canonical in DISEASE_ALIASES:
        if canonical == term and alias in lowered:
            return True
    return False


def _known_species(raw: list[str], options: list[str], question: str) -> list[str]:
    known = sorted({s for s in options if s and s != GENERAL_SPECIES}, key=len, reverse=True)
    by_lower = {s.lower(): s for s in known}
    result: list[str] = []
    for item in raw:
        value = str(item).strip()
        canonical = by_lower.get(value.lower()) or by_lower.get(canonical_species(value).lower())
        if canonical and canonical not in result:
            result.append(canonical)
    return result


def merge_plan(
    question: str,
    plan: PlannerIR,
    rule_ir: QueryIR,
    species_options: list[str],
) -> QueryIR:
    """Merge only validated LLM fields; rule-derived hard filters win."""
    warnings = list(rule_ir.warnings)
    species = _known_species(plan.species, species_options, question)
    lowered_question = question.lower()
    explicit_species = [
        item
        for item in species
        if item
        and (
            item.lower() in lowered_question
            or any(
                alias.lower() in lowered_question
                for alias, canonical in SPECIES_ALIASES.items()
                if canonical == item
            )
        )
    ]
    explicit_species = list(dict.fromkeys(explicit_species))
    inferred_species = set(species) - set(explicit_species)
    if inferred_species:
        warnings.append("llm_inferred_species_not_hard_filter")

    # Only an explicit, uniquely identified species can become a hard filter.
    hard_species = rule_ir.species_filter
    if hard_species is None and len(explicit_species) == 1:
        hard_species = next(iter(explicit_species))
    if len(explicit_species) > 1:
        warnings.append("llm_multiple_species_no_hard_filter")

    def _validated(raw: list[str], allowed: tuple[str, ...]) -> list[str]:
        values = _canonical_terms(raw, allowed)
        kept = [value for value in values if _mentioned(value, question)]
        if len(kept) < len(values):
            warnings.append("llm_inferred_facet_not_in_question")
        return kept

    water = _validated([*rule_ir.water_parameters, *plan.water_parameters], WATER_PARAMETERS)
    stages = _validated([*rule_ir.growth_stage, *plan.growth_stage], GROWTH_STAGES)
    diseases = _validated([*rule_ir.diseases, *plan.diseases], DISEASE_TERMS)

    constraints: list[dict] = []
    soft_constraints: list[dict] = []
    for item in plan.constraints:
        accepted = item.source == "explicit" and item.strength == "hard"
        filter_applied = False
        value = item.value
        # Only filters that the retrieval engine actually implements may be
        # promoted to hard.  A model saying "hard" is not enough.
        if item.name.lower() in {"species", "品种"}:
            value = canonical_species(item.value)
            if value not in explicit_species:
                accepted = False
                warnings.append("llm_constraint_rejected_not_explicit_species")
            else:
                filter_applied = hard_species == value
        elif accepted:
            accepted = False
            warnings.append("llm_constraint_not_implemented_as_hard")
        record = {
            "name": item.name,
            "value": value,
            "source": item.source,
            "strength": "hard" if accepted else "soft",
            "accepted_as_hard": accepted,
            "filter_applied": filter_applied,
            "scope": (
                "document_filter"
                if filter_applied
                else "retrieval_requirement"
                if accepted
                else "soft_context"
            ),
        }
        constraints.append(record)
        if not accepted:
            soft_constraints.append(record)

    def _values_for(field: str) -> list[str]:
        if field == "species":
            return [hard_species] if hard_species else list(explicit_species)
        if field == "growth_stage":
            return list(stages)
        if field == "water_parameters":
            return list(water)
        if field == "diseases":
            return list(diseases)
        if field == "year":
            return [str(rule_ir.requested_year)] if rule_ir.requested_year else []
        if field == "category":
            return [rule_ir.category_filter] if rule_ir.category_filter else []
        return []

    tasks: list[dict] = []
    subquestions: list[str] = []
    for item in plan.subquestions:
        text = item.question.strip()
        if not text or text == question:
            continue
        inherits = list(dict.fromkeys(item.inherits or DEFAULT_INHERITS))
        inherited: dict[str, list[str]] = {}
        applicable: dict[str, list[str]] = {}
        prefix: list[str] = []
        for field in inherits:
            values = _values_for(field)
            if not values:
                continue
            applicable[field] = values
            # A sub-question may already name one value of a multi-valued
            # facet (e.g. one growth stage).  Do not prepend the sibling
            # stages; that changes the question's meaning.
            if any(_mentioned(value, text) for value in values):
                continue
            inherited[field] = values
            if field == "category":
                # Category is applied as a document filter, not as query text.
                continue
            for value in values:
                if value not in prefix:
                    prefix.append(value)
        effective = " ".join([*prefix, text]).strip()
        unverified_species = [
            item for item in _species_in_text(text, species_options) if item not in explicit_species
        ]
        if unverified_species:
            warnings.append("llm_subquestion_added_unverified_species")
        subquestions.append(text)
        tasks.append(
            {
                "question": text,
                "facet": item.facet or "general",
                "inherits": inherits,
                "inherited_constraints": inherited,
                "applicable_constraints": applicable,
                "effective_query": effective,
                "soft_constraints": soft_constraints,
                "unverified_species_in_text": unverified_species,
                "source": "llm",
            }
        )

    return rule_ir.model_copy(
        update={
            "species": list(explicit_species) or rule_ir.species,
            "growth_stage": stages,
            "water_parameters": water,
            "diseases": diseases,
            "species_filter": hard_species,
            "intent": plan.intent or rule_ir.intent,
            "planner_source": "llm",
            "planner_confidence": plan.confidence,
            "planner_assumptions": list(plan.assumptions),
            "planner_constraints": constraints,
            "planner_subquestions": subquestions[:4],
            "planner_tasks": tasks[:4],
            "rewritten_query": (plan.rewritten_query or "").strip() or None,
            "warnings": list(dict.fromkeys(warnings)),
        }
    )


@dataclass(slots=True)
class PlannerOutcome:
    ir: QueryIR
    plan: PlannerIR | None
    used_llm: bool
    error: str | None
    duration_ms: float
    attempts: int = 1

    def trace(self) -> dict:
        return {
            "enabled": True,
            "used_llm": self.used_llm,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 1),
            "attempts": self.attempts,
            "plan": self.plan.model_dump() if self.plan else None,
            "original_question": self.ir.original_question,
            "hard_filter": self.ir.species_filter,
            "subquestions": self.ir.planner_subquestions,
            "tasks": self.ir.planner_tasks,
            "constraints": self.ir.planner_constraints,
            "assumptions": self.ir.planner_assumptions,
        }


class LLMQueryPlanner:
    def __init__(self, completer: Completer, config: Settings | None = None) -> None:
        self.completer = completer
        self.config = config or settings

    async def plan(
        self,
        question: str,
        rule_ir: QueryIR,
        species_options: list[str],
    ) -> PlannerOutcome:
        started = time.perf_counter()
        last_error: Exception | None = None
        attempts = 0
        # Some reasoning models sometimes truncate a JSON object even when the
        # transport returns 200.  Retry once with a larger budget only on a
        # parse/schema error; never retry a network/configuration error.
        for attempt in range(2):
            attempts = attempt + 1
            try:
                raw = await asyncio.wait_for(
                    self.completer.complete(
                        build_planner_messages(question, rule_ir, species_options),
                        max_tokens=self.config.planner_max_tokens + attempt * 1000,
                        temperature=self.config.planner_temperature,
                        response_format={"type": "json_object"},
                    ),
                    timeout=self.config.planner_timeout_s,
                )
            except Exception as exc:
                last_error = exc
                # Reasoning models sometimes return HTTP 200 with no visible
                # content because the budget was spent on reasoning.  Retry
                # once with a larger budget; do not retry network/timeouts.
                if "empty content" in str(exc).lower() or "no choices" in str(exc).lower():
                    continue
                break
            try:
                plan = parse_planner_json(raw)
                ir = merge_plan(question, plan, rule_ir, species_options)
                return PlannerOutcome(
                    ir=ir,
                    plan=plan,
                    used_llm=True,
                    error=None,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    attempts=attempts,
                )
            except ValueError as exc:
                last_error = exc
        return PlannerOutcome(
            ir=rule_ir,
            plan=None,
            used_llm=False,
            error=f"{last_error.__class__.__name__}: {last_error}"
            if last_error
            else "planner_failed",
            duration_ms=(time.perf_counter() - started) * 1000,
            attempts=attempts,
        )


def planner_from_generator(generator: object) -> LLMQueryPlanner | None:
    complete = getattr(generator, "complete", None)
    if not callable(complete):
        return None
    return LLMQueryPlanner(generator)  # type: ignore[arg-type]
