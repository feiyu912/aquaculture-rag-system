"""Facet-level evidence requirements and targeted-query construction."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.query.ir import QueryIR
from app.retrieval.bm25 import CUSTOM_TERMS


@dataclass(slots=True)
class Requirement:
    key: str
    label: str
    terms: list[str]
    covered: bool = False
    matched_terms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "terms": self.terms,
            "covered": self.covered,
            "matched_terms": self.matched_terms,
        }


def build_requirements(ir: QueryIR | None) -> list[Requirement]:
    if ir is None:
        return []
    requirements: list[Requirement] = []
    for index, parameter in enumerate(ir.water_parameters):
        requirements.append(Requirement(f"water:{index}", "水质指标", [parameter]))
    for index, disease in enumerate(ir.diseases):
        requirements.append(Requirement(f"disease:{index}", "疾病/症状", [disease]))
    for index, stage in enumerate(ir.growth_stage):
        requirements.append(Requirement(f"stage:{index}", "养殖阶段", [stage]))
    return requirements


def assess_requirements(
    requirements: list[Requirement],
    texts: list[str],
) -> list[Requirement]:
    merged = "\n".join(texts).lower()
    for requirement in requirements:
        matched = [term for term in requirement.terms if term.lower() in merged]
        requirement.matched_terms = matched
        requirement.covered = len(matched) == len(requirement.terms)
    return requirements


def missing_terms(requirements: list[Requirement]) -> list[str]:
    terms: list[str] = []
    for requirement in requirements:
        if requirement.covered:
            continue
        terms.extend(term for term in requirement.terms if term not in requirement.matched_terms)
    return list(dict.fromkeys(terms))


def build_supplemental_query(
    question: str,
    requirements: list[Requirement],
    gate_missing_terms: list[str],
    *,
    max_terms: int = 6,
) -> str | None:
    terms = [*missing_terms(requirements), *gate_missing_terms]
    # Only retry when the gap contains a domain-bearing term.  This avoids a
    # second identical search for an out-of-domain question.
    if not any(term in CUSTOM_TERMS for term in terms):
        return None
    deduped = [term for term in dict.fromkeys(terms) if term][:max_terms]
    if not deduped:
        return None
    return " ".join([question, *deduped])
