"""Chunk-level retrieval metrics used by the thesis evaluation scripts."""

from __future__ import annotations

import math
from typing import Any


def dcg(grades: list[int], k: int) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades[:k]))


def score_ranking(
    ranked: list[str],
    gold: dict[str, int],
    ks: tuple[int, ...] = (5, 10),
) -> dict[str, Any]:
    """Score one ranked chunk-id list against graded gold chunks.

    ``gold`` maps a chunk ID to relevance grade.  A retrieved item not in gold
    contributes zero; duplicate ranked IDs should be removed by the caller.
    """
    ranked = list(dict.fromkeys(ranked))
    relevant = set(gold)
    first = next(
        (index for index, chunk_id in enumerate(ranked, start=1) if chunk_id in relevant), None
    )
    result: dict[str, Any] = {
        "first_relevant_rank": first,
        "mrr@10": round(1.0 / first, 4) if first and first <= 10 else 0.0,
        "gold_rank": {
            chunk_id: next(
                (i for i, value in enumerate(ranked, start=1) if value == chunk_id), None
            )
            for chunk_id in relevant
        },
    }
    ideal = sorted(gold.values(), reverse=True)
    for k in ks:
        retrieved = set(ranked[:k])
        result[f"recall@{k}"] = (
            round(len(retrieved & relevant) / len(relevant), 4) if relevant else 0.0
        )
        # Keep every position: an irrelevant hit at rank 1 must still push the
        # relevant item down.  Filtering to relevant-only items (the old
        # behaviour) re-ranked them from position 1 and overestimated nDCG.
        gained = [gold.get(chunk_id, 0) for chunk_id in ranked[:k]]
        ideal_dcg = dcg(ideal, k)
        result[f"ndcg@{k}"] = round(dcg(gained, k) / ideal_dcg, 4) if ideal_dcg else 0.0
    return result
