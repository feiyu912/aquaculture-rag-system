"""LLM-assisted natural-language to typed-query-plan conversion.

The LLM proposes a plan; deterministic validators decide what may become a
retrieval filter.  This module never lets an inferred species, year, category,
or regulation status become a hard constraint.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings, settings
from app.query.ir import (
    DISEASE_TERMS,
    GROWTH_STAGES,
    WATER_ALIASES,
    WATER_PARAMETERS,
    QueryIR,
)
from app.species import GENERAL_SPECIES

Intent = Literal["fact", "complex", "regulation", "calculation"]
Strength = Literal["hard", "soft"]
Source = Literal["explicit", "inferred"]


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
    inherits: list[str] = Field(default_factory=list)


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
4. 复杂问题拆成 1-4 个可独立检索的子问题；子问题通过 inherits 声明继承原问题的品种/阶段。
5. 不要编造疾病诊断或用药剂量。输出必须是合法 JSON。"""


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
    result: list[str] = []
    for item in raw:
        key = str(item).strip().lower()
        term = aliases.get(key)
        if term and term not in result:
            result.append(term)
    return result


def _mentioned(term: str, question: str) -> bool:
    if term in question:
        return True
    lowered = question.lower()
    for alias, canonical in WATER_ALIASES:
        if canonical == term and alias in lowered:
            return True
    return False


def _known_species(raw: list[str], options: list[str], question: str) -> list[str]:
    known = sorted({s for s in options if s and s != GENERAL_SPECIES}, key=len, reverse=True)
    by_lower = {s.lower(): s for s in known}
    result: list[str] = []
    for item in raw:
        value = str(item).strip()
        canonical = by_lower.get(value.lower())
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
    explicit_species = {item for item in species if item and item.lower() in question.lower()}
    inferred_species = set(species) - explicit_species
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
    for item in plan.constraints:
        accepted = item.source == "explicit" and item.strength == "hard"
        filter_applied = False
        if item.name.lower() in {"species", "品种"}:
            if item.value not in explicit_species:
                accepted = False
                warnings.append("llm_constraint_rejected_not_explicit_species")
            else:
                filter_applied = hard_species == item.value
        constraints.append(
            {
                "name": item.name,
                "value": item.value,
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
        )

    subquestions = [
        item.question.strip()
        for item in plan.subquestions
        if item.question.strip() and item.question.strip() != question
    ][:4]

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
            "planner_subquestions": subquestions,
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
            "hard_filter": self.ir.species_filter,
            "subquestions": self.ir.planner_subquestions,
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
                raw = await self.completer.complete(
                    build_planner_messages(question, rule_ir, species_options),
                    max_tokens=self.config.planner_max_tokens + attempt * 1000,
                    temperature=self.config.planner_temperature,
                    response_format={"type": "json_object"},
                )
            except Exception as exc:
                last_error = exc
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
