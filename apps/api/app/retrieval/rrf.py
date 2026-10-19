from __future__ import annotations


def rrf_fuse(
    rankings: list[list[str]],
    k: int = 60,
    weights: list[float] | None = None,
    limit: int | None = None,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over multiple ranked ID lists.

    The score is sum(weight_i / (k + rank_i)). Documents missing from a list
    simply receive no contribution from it. Ties keep first-seen order.
    """
    if weights is None:
        weights = [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("weights and rankings must have the same length")

    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    cursor = 0
    for ranking, weight in zip(rankings, weights):
        for rank, doc_id in enumerate(ranking, start=1):
            if doc_id not in scores:
                scores[doc_id] = 0.0
                first_seen[doc_id] = cursor
                cursor += 1
            scores[doc_id] += weight / (k + rank)

    fused = sorted(scores.items(), key=lambda item: (-item[1], first_seen[item[0]]))
    return fused[:limit] if limit is not None else fused
