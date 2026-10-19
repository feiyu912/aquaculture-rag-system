from __future__ import annotations

from dataclasses import dataclass, field

from app.retrieval.bm25 import CUSTOM_TERMS, tokenize

# Generic query words that should not make an unrelated document look relevant.
GATE_STOPWORDS = {
    "养殖",
    "水产",
    "要求",
    "标准",
    "范围",
    "情况",
    "问题",
    "一下",
    "请问",
    "告诉",
    "介绍",
    "有关",
    "相关",
    "是否",
    "能否",
    "应该",
    "需要",
    "可以",
    "怎么样",
    "怎样",
    "为什么",
    "治疗",
    "防治",
}

# Broad domain words still carry topical signal even when they are not in the
# custom BM25 dictionary.
EXTRA_DOMAIN_TERMS = {
    "水质",
    "溶氧",
    "ph",
    "mg/l",
    "ppm",
    "对虾",
    "河蟹",
    "虾类",
    "蟹类",
    "鱼类",
    "病害",
    "饲料",
}


@dataclass(frozen=True, slots=True)
class Sufficiency:
    sufficient: bool
    reason: str
    query_terms: list[str]
    matched_terms: list[str]
    matched_weight: float
    total_weight: float
    coverage: float
    best_index: int | None
    missing_terms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "sufficient": self.sufficient,
            "reason": self.reason,
            "query_terms": self.query_terms,
            "matched_terms": self.matched_terms,
            "matched_weight": self.matched_weight,
            "total_weight": self.total_weight,
            "coverage": round(self.coverage, 3),
            "best_index": self.best_index,
            "missing_terms": self.missing_terms,
        }


def query_terms(question: str) -> list[str]:
    return [term for term in tokenize(question) if term not in GATE_STOPWORDS]


def _weight(term: str, domain_terms: set[str]) -> float:
    return 3.0 if term in domain_terms else 1.0


def _contains(term: str, text: str, text_terms: set[str]) -> bool:
    """Match exact tokens first, then CJK substrings for abbreviations.

    "对虾" should match "凡纳滨对虾" without hard-coding aliases; the substring
    rule is limited to terms of two or more characters.
    """
    if term in text_terms:
        return True
    return len(term) >= 2 and term in text


def assess_evidence(
    question: str,
    texts: list[str],
    *,
    min_terms: int = 2,
    min_weight: float = 3.0,
    min_coverage: float = 0.3,
    domain_terms: set[str] | None = None,
) -> Sufficiency:
    """Cheap lexical sufficiency check before generation.

    This is intentionally conservative. It is not a semantic entailment model;
    it only prevents the most obvious failure mode: returning unrelated chunks
    for an out-of-domain question and presenting them as evidence.
    """
    terms = query_terms(question)
    if not terms:
        return Sufficiency(False, "no_query_terms", [], [], 0.0, 0.0, 0.0, None)

    dictionary = set(CUSTOM_TERMS) | EXTRA_DOMAIN_TERMS | set(domain_terms or ())
    total_weight = sum(_weight(term, dictionary) for term in terms)
    best: Sufficiency | None = None
    candidates: list[Sufficiency] = []
    for index, text in enumerate(texts):
        lowered = text.lower()
        text_terms = set(tokenize(text))
        matched = [term for term in terms if _contains(term, lowered, text_terms)]
        matched_weight = sum(_weight(term, dictionary) for term in matched)
        coverage = matched_weight / total_weight if total_weight else 0.0
        candidates.append(
            Sufficiency(
                sufficient=False,
                reason="weak_overlap",
                query_terms=terms,
                matched_terms=matched,
                matched_weight=matched_weight,
                total_weight=total_weight,
                coverage=coverage,
                best_index=index,
            )
        )

    # A multi-part question may be covered by different evidence blocks. Check
    # the union as well, otherwise a correct retrieval is rejected just because
    # no single parent contains every query term.
    if texts:
        merged = "\n".join(texts).lower()
        union_terms: set[str] = set()
        for text in texts:
            union_terms.update(tokenize(text))
        matched = [term for term in terms if _contains(term, merged, union_terms)]
        matched_weight = sum(_weight(term, dictionary) for term in matched)
        candidates.append(
            Sufficiency(
                sufficient=False,
                reason="weak_overlap",
                query_terms=terms,
                matched_terms=matched,
                matched_weight=matched_weight,
                total_weight=total_weight,
                coverage=matched_weight / total_weight if total_weight else 0.0,
                best_index=None,
            )
        )

    for candidate in candidates:
        if best is None or (candidate.matched_weight, len(candidate.matched_terms)) > (
            best.matched_weight,
            len(best.matched_terms),
        ):
            best = candidate

    if best is None:
        return Sufficiency(False, "no_evidence", terms, [], 0.0, total_weight, 0.0, None)

    strong_enough = (
        len(best.matched_terms) >= min_terms
        and best.matched_weight >= min_weight
        and best.coverage >= min_coverage
    )
    # A single domain term ("溶解氧", "盐度") is a valid focused query.
    single_domain = (
        len(terms) == 1 and len(best.matched_terms) == 1 and best.matched_weight >= min_weight
    )
    if strong_enough or single_domain:
        return Sufficiency(
            sufficient=True,
            reason="matched",
            query_terms=best.query_terms,
            matched_terms=best.matched_terms,
            matched_weight=best.matched_weight,
            total_weight=best.total_weight,
            coverage=best.coverage,
            best_index=best.best_index,
        )
    return Sufficiency(
        sufficient=False,
        reason=best.reason,
        query_terms=best.query_terms,
        matched_terms=best.matched_terms,
        matched_weight=best.matched_weight,
        total_weight=best.total_weight,
        coverage=best.coverage,
        best_index=best.best_index,
        missing_terms=[term for term in best.query_terms if term not in best.matched_terms],
    )