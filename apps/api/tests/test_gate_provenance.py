from __future__ import annotations

import uuid

from app.retrieval.service import Evidence, _assess_with_requirements


def test_gate_uses_heading_and_title_metadata():
    item = Evidence(
        source_index=1,
        document_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        parent_chunk_id=uuid.uuid4(),
        child_chunk_id=uuid.uuid4(),
        title="DB36 中华绒螯蟹池塘培育扣蟹技术规程",
        version_no=1,
        page=7,
        quote="溶氧量5mg/L以上。",
        content="溶氧量5mg/L以上。",
        location=None,
        score=1.0,
        species=["中华绒螯蟹"],
        heading_path=["8.1水质指标"],
    )
    gate = _assess_with_requirements(
        "扣蟹培育的溶解氧要求是什么？",
        [item],
        [],
        ["中华绒螯蟹"],
        fallback_reason=None,
    )
    assert gate.sufficient
    assert "扣蟹" in gate.matched_terms


def test_latest_regulation_without_effective_date_is_refused():
    from app.query.ir import build_query_ir
    from app.retrieval.service import _apply_current_regulation_gate
    from app.retrieval.sufficiency import Sufficiency

    ir = build_query_ir("2026年最新禁用渔药名单里具体有哪些品种？", ["通用", "中华绒螯蟹"])
    gate = Sufficiency(True, "matched", ["渔药"], ["渔药"], 3.0, 3.0, 1.0, 0)
    refused = _apply_current_regulation_gate(ir, gate)
    assert refused.sufficient is False
    assert refused.reason == "current_regulation_unverified"
