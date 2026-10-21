from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.retrieval_metrics import score_ranking


def test_metrics_reward_rank_and_grades():
    gold = {"A": 2, "B": 1}
    perfect = score_ranking(["A", "B", "X"], gold, ks=(5,))
    assert perfect["recall@5"] == 1.0
    assert perfect["ndcg@5"] == 1.0
    assert perfect["mrr@10"] == 1.0

    lower = score_ranking(["X", "B", "A"], gold, ks=(5,))
    assert lower["recall@5"] == 1.0
    assert lower["mrr@10"] == 0.5
    assert 0 < lower["ndcg@5"] < 1.0

    missing = score_ranking(["X", "Y"], gold, ks=(5,))
    assert missing["recall@5"] == 0.0
    assert missing["ndcg@5"] == 0.0
    assert missing["mrr@10"] == 0.0


def test_ndcg_penalises_irrelevant_hits_in_place():
    gold = {"correct": 2}
    assert score_ranking(["correct"], gold, ks=(5,))["ndcg@5"] == 1.0
    # 1 / log2(3): the irrelevant hit occupies rank 1 and pushes gold to rank 2.
    assert score_ranking(["wrong", "correct"], gold, ks=(5,))["ndcg@5"] == 0.6309
    assert score_ranking(["wrong", "correct"], gold, ks=(10,))["ndcg@10"] == 0.6309
    # More irrelevant hits in front must lower the score further.
    assert score_ranking(["w1", "w2", "correct"], gold, ks=(5,))["ndcg@5"] < 0.6309


def test_ndcg_respects_grades_and_dedupes_ranked_ids():
    gold = {"A": 2, "B": 1}
    assert score_ranking(["A", "B"], gold, ks=(5,))["ndcg@5"] == 1.0
    swapped = score_ranking(["B", "A"], gold, ks=(5,))["ndcg@5"]
    assert 0 < swapped < 1.0
    duplicated = score_ranking(["A", "A", "B"], gold, ks=(5,))
    assert duplicated["ndcg@5"] == 1.0
    assert duplicated["recall@5"] == 1.0


def test_real_eval_dataset_is_labelled_and_reviewable():
    root = Path(__file__).resolve().parents[3]
    path = root / "eval" / "real_questions_v1.jsonl"
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(cases) >= 50
    assert len({case["id"] for case in cases}) == len(cases)
    answerable = [case for case in cases if not case["expect_insufficient"]]
    assert len(answerable) >= 50
    for case in answerable:
        assert case["gold"], case["id"]
        assert all(item.get("chunk_id") and item.get("page") for item in case["gold"])
        assert case["annotation_status"] == "ai_assisted_pending_human_review"
        assert case["review_required"] is True
