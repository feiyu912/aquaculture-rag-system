from __future__ import annotations

import uuid

from app.retrieval.requirements import Requirement, build_targeted_queries, term_present
from app.retrieval.service import TARGETED_SKIP_REASONS


def test_one_query_per_uncovered_requirement():
    requirements = [
        Requirement("water:0", "水质指标", ["盐度"]),
        Requirement("water:1", "水质指标", ["酸碱度"], covered=True, matched_terms=["酸碱度"]),
        Requirement("water:2", "水质指标", ["溶解氧"], matched_terms=[]),
    ]
    targets = build_targeted_queries("育苗池水质怎么调？", requirements, [])
    assert [target["key"] for target in targets] == ["water:0", "water:2"]
    assert targets[0]["query"] == "盐度"
    assert targets[1]["terms"] == ["溶解氧"]


def test_covered_requirements_produce_no_retry():
    requirements = [Requirement("water:0", "水质指标", ["盐度"], covered=True, matched_terms=["盐度"])]
    assert build_targeted_queries("盐度多少合适？", requirements, []) == []


def test_gate_terms_are_used_when_no_structured_requirement_exists():
    targets = build_targeted_queries("越冬期怎么管理？", [], ["水温", "溶解氧"])
    assert len(targets) == 1
    assert targets[0]["key"] == "gate"
    assert targets[0]["terms"] == ["水温", "溶解氧"]


def test_non_domain_gate_terms_do_not_trigger_a_retry():
    assert build_targeted_queries("这个怎么样？", [], ["这个"]) == []


def test_retries_are_deduped_and_capped():
    requirements = [Requirement(f"water:{i}", "水质指标", ["盐度"]) for i in range(3)]
    targets = build_targeted_queries("盐度多少？", requirements, [], max_targets=2)
    assert len(targets) == 1


def test_skip_reasons_include_non_retryable_gates():
    assert {"no_query_terms", "no_evidence", "current_regulation_unverified"} <= TARGETED_SKIP_REASONS


def _evidence(content: str, heading: str = "", score: float = 0.5):
    from app.retrieval.service import Evidence

    return Evidence(
        source_index=1,
        document_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        parent_chunk_id=uuid.uuid4(),
        child_chunk_id=uuid.uuid4(),
        title="t",
        version_no=1,
        page=1,
        quote=content,
        content=content,
        location=None,
        score=score,
        heading_path=[heading] if heading else [],
    )


def test_covering_evidence_takes_the_slots():
    from app.retrieval.service import _covering_first

    pooled = [_evidence("水温 18℃", score=0.9), _evidence("亚硝酸盐低于0.05", score=0.1)]
    reordered = _covering_first(pooled, ["亚硝酸盐"])
    assert reordered[0].content.startswith("亚硝酸盐")
    assert len(reordered) == 2


def test_covering_first_keeps_order_when_nothing_covers():
    from app.retrieval.service import _covering_first

    pooled = [_evidence("水温 18℃", score=0.9), _evidence("水色 黄绿", score=0.2)]
    assert _covering_first(pooled, ["亚硝酸盐"]) == pooled


def test_heading_counts_for_coverage():
    assert term_present("扣蟹培育", "正文\n扣蟹培育池")
    assert term_present("酸碱度", "pH值7.5~8.5")
