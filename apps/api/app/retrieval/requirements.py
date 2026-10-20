"""Facet-level evidence requirements and targeted-query construction."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.query.ir import QueryIR
from app.retrieval.bm25 import CUSTOM_TERMS

# The IR stores canonical parameter names; standards often use a different
# surface form (pH vs 酸碱度, 亲本 vs 亲虾/亲蟹).  Requirement coverage must accept
# the document-side wording, otherwise a correct chunk can never cover a facet.
TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "酸碱度": ("ph", "ph值"),
    "溶解氧": ("溶氧", "do"),
    "氨氮": ("氨态氮", "总氨氮"),
    "亚硝酸盐": ("亚硝酸盐氮", "no2"),
    "亲本": ("亲虾", "亲蟹", "亲体", "种虾", "种蟹"),
    "扣蟹培育": ("扣蟹", "培育扣蟹", "蟹种培育"),
}


def term_present(term: str, text: str) -> bool:
    lowered = text.lower()
    if term.lower() in lowered:
        return True
    return any(alias in lowered for alias in TERM_ALIASES.get(term, ()))


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
    merged = "\n".join(texts)
    for requirement in requirements:
        matched = [term for term in requirement.terms if term_present(term, merged)]
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


def build_targeted_queries(
    question: str,
    requirements: list[Requirement],
    gate_missing_terms: list[str],
    *,
    max_targets: int = 2,
    max_terms: int = 3,
) -> list[dict]:
    """One narrow query per uncovered requirement instead of one diluted retry.

    Asking for "盐度 酸碱度 水温" at once pulls documents that mention any one of
    them; asking for each separately lets the evidence gate judge coverage
    requirement by requirement.  Gate-level missing terms are only used when no
    structured requirement exists.
    """
    targets: list[dict] = []
    for requirement in requirements:
        if requirement.covered:
            continue
        terms = [
            term for term in requirement.terms if term not in requirement.matched_terms
        ] or list(requirement.terms)
        domain_terms = [term for term in terms if term in CUSTOM_TERMS]
        terms = (domain_terms or terms)[:max_terms]
        if not terms:
            continue
        targets.append(
            {
                "key": requirement.key,
                "label": requirement.label,
                "terms": terms,
                # Facet-only query: appending the missing word to the original
                # question barely changes the ranking (the question still
                # dominates), so the retry returns the same top-k.  Searching
                # the facet alone surfaces the source that actually states it;
                # the unchanged gate then judges the merged evidence.
                "query": " ".join(terms),
                "source": "requirement",
            }
        )
    if not targets:
        domain_terms = [term for term in gate_missing_terms if term in CUSTOM_TERMS]
        if domain_terms:
            terms = domain_terms[:max_terms]
            targets.append(
                {
                    "key": "gate",
                    "label": "gate_terms",
                    "terms": terms,
                    "query": " ".join([question, *terms]),
                    "source": "gate",
                }
            )
    deduped: list[dict] = []
    seen: set[str] = set()
    for target in targets:
        if target["query"] in seen:
            continue
        seen.add(target["query"])
        deduped.append(target)
    return deduped[:max_targets]


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
