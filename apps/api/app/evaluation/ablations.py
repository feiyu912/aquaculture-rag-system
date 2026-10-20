"""Pure helpers for the retrieval ablation runner.

Keeping configuration, validation, and metric aggregation here makes the CLI
thin and lets the regression suite test the evaluation contract without a live
PostgreSQL/Qdrant stack.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

ABLATION_FLAGS = (
    "enable_query_ir",
    "enable_graph_expansion",
    "enable_evidence_requirements",
    "enable_targeted_retrieval",
    "enable_query_decomposition",
    "enable_adaptive_routing",
)

DEFAULT_CONFIGS: dict[str, dict[str, bool]] = {
    # Query IR is part of the current baseline.  It must be explicit here so
    # apply_config() cannot silently inherit it from the shell environment.
    "baseline": {"enable_query_ir": True},
    "no_query_ir": {"enable_query_ir": False},
    "graph": {"enable_query_ir": True, "enable_graph_expansion": True},
    "requirements": {"enable_query_ir": True, "enable_evidence_requirements": True},
    "requirements_retry": {
        "enable_query_ir": True,
        "enable_evidence_requirements": True,
        "enable_targeted_retrieval": True,
    },
    "decomposition": {"enable_query_ir": True, "enable_query_decomposition": True},
    "adaptive": {"enable_query_ir": True, "enable_adaptive_routing": True},
    "full_optional": {
        "enable_query_ir": True,
        "enable_graph_expansion": True,
        "enable_evidence_requirements": True,
        "enable_targeted_retrieval": True,
        "enable_query_decomposition": True,
    },
    "full_optional_adaptive": {
        "enable_query_ir": True,
        "enable_graph_expansion": True,
        "enable_evidence_requirements": True,
        "enable_targeted_retrieval": True,
        "enable_query_decomposition": True,
        "enable_adaptive_routing": True,
    },
}


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    """Return human-readable dataset errors; empty means valid."""
    errors: list[str] = []
    if not cases:
        errors.append("dataset is empty")
        return errors
    seen: set[str] = set()
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("id") or f"case-{index}")
        if case_id in seen:
            errors.append(f"{case_id}: duplicate id")
        seen.add(case_id)
        if not str(case.get("question") or "").strip():
            errors.append(f"{case_id}: missing question")
        if case.get("expect_insufficient"):
            continue
        if not case.get("gold_title"):
            errors.append(f"{case_id}: missing gold_title")
        pages = case.get("gold_pages")
        if not pages or not all(isinstance(page, int) and page > 0 for page in pages):
            errors.append(f"{case_id}: gold_pages must be positive integers")
    return errors


def apply_config(settings_obj: Any, overrides: dict[str, bool]) -> None:
    """Reset every ablation flag, then apply exactly one config."""
    unknown = set(overrides) - set(ABLATION_FLAGS)
    if unknown:
        raise ValueError(f"unknown ablation flags: {sorted(unknown)}")
    for flag in ABLATION_FLAGS:
        setattr(settings_obj, flag, False)
    for flag, value in overrides.items():
        setattr(settings_obj, flag, bool(value))


def snapshot_flags(settings_obj: Any) -> dict[str, bool]:
    return {flag: bool(getattr(settings_obj, flag)) for flag in ABLATION_FLAGS}


def restore_flags(settings_obj: Any, snapshot: dict[str, bool]) -> None:
    for flag, value in snapshot.items():
        setattr(settings_obj, flag, value)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def summarize(
    config_name: str,
    details: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate one config. Hit/MRR use answerable cases; refusal uses OOD cases."""
    if len(details) != len(cases):
        raise ValueError("details and cases must have the same length")
    answerable = [
        detail for detail, case in zip(details, cases) if not case.get("expect_insufficient")
    ]
    expected_refusal = [
        detail for detail, case in zip(details, cases) if case.get("expect_insufficient")
    ]
    retrieval_ms = [float(item.get("retrieval_ms") or 0.0) for item in details]
    sorted_ms = sorted(retrieval_ms)
    p95 = sorted_ms[max(0, int(len(sorted_ms) * 0.95) - 1)] if sorted_ms else 0.0
    route_counts = Counter(str(item.get("route") or "unknown") for item in details)
    return {
        "config": config_name,
        "cases": len(details),
        "answerable_cases": len(answerable),
        "hit_rate": _mean([1.0 if item.get("hit") else 0.0 for item in answerable]),
        "mrr": _mean([float(item.get("mrr") or 0.0) for item in answerable]),
        "false_refusal_rate": _mean([1.0 if item.get("refused") else 0.0 for item in answerable]),
        "refusal_rate": _mean([1.0 if item.get("refused") else 0.0 for item in expected_refusal]),
        "avg_sources": _mean([float(item.get("sources") or 0) for item in details]),
        "avg_retrieval_ms": _mean(retrieval_ms),
        "p95_retrieval_ms": round(p95, 1),
        "targeted_cases": sum(1 for item in details if item.get("targeted")),
        "routes": dict(sorted(route_counts.items())),
    }
