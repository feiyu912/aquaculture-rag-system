"""Optional semantic claim/citation check.

This is a cosine-similarity screen over BGE-M3 embeddings, NOT an NLI model.
It can upgrade a lexical ``unverified``/``weak`` claim when the cited quote is
semantically close, but it must never be reported as factual entailment.
Disabled by default because it adds one embedding batch per answer.
"""

from __future__ import annotations

import math
from typing import Protocol

from app.generation.claims import CITATION_RE, verify_claims


class EmbeddingModel(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def verify_claims_semantic(
    answer: str,
    evidence: list[dict],
    embedder: EmbeddingModel,
    *,
    threshold: float = 0.65,
) -> list[dict]:
    """Combine lexical checks with an optional BGE-M3 cosine screen.

    The lexical result stays in ``lexical_status``.  A claim is only upgraded
    to ``supported`` when its best cited quote reaches ``threshold``; otherwise
    the lexical status is preserved.  ``method`` names the method that produced
    the final status so a thesis can separate lexical from semantic results.
    """
    lexical_claims = verify_claims(answer, evidence)
    quotes: dict[int, str] = {}
    for item in evidence:
        index = item.get("index", item.get("source_index"))
        quote = item.get("quote") or item.get("content") or ""
        if index is not None and quote:
            quotes[int(index)] = quote

    cited = [claim for claim in lexical_claims if claim.get("cited_indices")]
    if not cited:
        return lexical_claims

    claim_texts = [CITATION_RE.sub("", claim["claim"]).strip() for claim in cited]
    quote_indices = sorted(
        {index for claim in cited for index in claim["cited_indices"] if index in quotes}
    )
    quote_texts = [quotes[index] for index in quote_indices]
    vectors = embedder.embed_documents([*claim_texts, *quote_texts])
    if len(vectors) != len(claim_texts) + len(quote_texts):
        raise ValueError("embedder returned the wrong number of vectors")
    claim_vectors = vectors[: len(claim_texts)]
    quote_vectors = {
        index: vectors[len(claim_texts) + offset] for offset, index in enumerate(quote_indices)
    }

    for claim, vector in zip(cited, claim_vectors, strict=True):
        scores = {
            index: _cosine(vector, quote_vectors[index])
            for index in claim["cited_indices"]
            if index in quote_vectors
        }
        if not scores:
            continue
        best_index, best_score = max(scores.items(), key=lambda item: item[1])
        claim["semantic_score"] = round(best_score, 3)
        claim["semantic_index"] = best_index
        claim["lexical_status"] = claim["status"]
        if claim["status"] != "supported" and best_score >= threshold:
            claim["status"] = "supported"
            claim["score"] = round(best_score, 3)
            claim["method"] = "bge_m3_cosine_v0"
            claim["matched_terms"] = []
        elif claim["status"] == "unverified" and best_score >= threshold * 0.75:
            claim["status"] = "weak"
            claim["score"] = round(best_score, 3)
            claim["method"] = "bge_m3_cosine_v0"

    return lexical_claims
