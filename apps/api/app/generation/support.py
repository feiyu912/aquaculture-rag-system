from __future__ import annotations

import re
from dataclasses import dataclass

from app.retrieval.bm25 import STOPWORDS, tokenize

CITATION_RE = re.compile(r"[\[【][^\]】]{1,80}[\]】]")

# Placeholder for the thesis' support-verification stage. Lexical overlap can
# only flag obvious cases; it is not an entailment model and must not be
# reported as factual correctness.
SUPPORT_METHOD = "lexical_overlap_v0"


@dataclass(slots=True)
class SupportAssessment:
    status: str
    score: float
    method: str
    matched_terms: list[str]

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "score": round(self.score, 3),
            "method": self.method,
            "matched_terms": self.matched_terms,
        }


def verify_support(claim: str, quote: str) -> SupportAssessment:
    claim_terms = {
        term
        for term in tokenize(CITATION_RE.sub("", claim))
        if term not in STOPWORDS and len(term) > 1
    }
    quote_terms = set(tokenize(quote))
    matched = sorted(claim_terms & quote_terms)
    score = len(matched) / len(claim_terms) if claim_terms else 0.0
    if score >= 0.6:
        status = "supported"
    elif score >= 0.3:
        status = "weak"
    else:
        status = "unverified"
    return SupportAssessment(status=status, score=score, method=SUPPORT_METHOD, matched_terms=matched)
