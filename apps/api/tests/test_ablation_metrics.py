from __future__ import annotations

from app.evaluation.ablations import (
    ABLATION_FLAGS,
    DEFAULT_CONFIGS,
    apply_config,
    snapshot_flags,
    summarize,
    validate_cases,
)


class _Settings:
    pass


def test_every_ablation_flag_is_covered_by_a_config():
    configured = set().union(*(set(config) for config in DEFAULT_CONFIGS.values()))
    assert configured == set(ABLATION_FLAGS)


def test_apply_config_resets_flags_before_enabling():
    settings = _Settings()
    for flag in ABLATION_FLAGS:
        setattr(settings, flag, True)
    apply_config(settings, {"enable_graph_expansion": True})
    assert settings.enable_graph_expansion is True
    assert settings.enable_adaptive_routing is False
    assert settings.enable_query_decomposition is False


def test_snapshot_and_restore_preserve_flags():
    settings = _Settings()
    for index, flag in enumerate(ABLATION_FLAGS):
        setattr(settings, flag, bool(index % 2))
    snapshot = snapshot_flags(settings)
    apply_config(settings, {"enable_adaptive_routing": True})
    assert settings.enable_adaptive_routing is True
    for flag, value in snapshot.items():
        setattr(settings, flag, value)
    assert snapshot_flags(settings) == snapshot


def test_validate_cases_rejects_incomplete_ground_truth():
    errors = validate_cases(
        [
            {"id": "q1", "question": "问题", "gold_title": None, "gold_pages": []},
            {"id": "q1", "question": "", "expect_insufficient": True},
        ]
    )
    assert any("gold_title" in error for error in errors)
    assert any("gold_pages" in error for error in errors)
    assert any("duplicate" in error for error in errors)
    assert any("question" in error for error in errors)


def test_summarize_uses_answerable_and_ood_slices():
    cases = [
        {"id": "q1"},
        {"id": "q2", "expect_insufficient": True},
    ]
    details = [
        {
            "hit": True,
            "mrr": 1.0,
            "refused": False,
            "sources": 3,
            "retrieval_ms": 10,
            "targeted": False,
            "route": "simple",
        },
        {
            "hit": False,
            "mrr": 0.0,
            "refused": True,
            "sources": 0,
            "retrieval_ms": 20,
            "targeted": False,
            "route": "simple",
        },
    ]
    summary = summarize("baseline", details, cases)
    assert summary["hit_rate"] == 1.0
    assert summary["mrr"] == 1.0
    assert summary["refusal_rate"] == 1.0
    assert summary["false_refusal_rate"] == 0.0
    assert summary["avg_retrieval_ms"] == 15.0
