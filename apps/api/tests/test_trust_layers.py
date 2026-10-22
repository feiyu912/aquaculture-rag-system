"""Anti-pollution regression tests for the layered trust policy.

These tests are the executable form of the rule "third-party QA must never be
cited as evidence".  They are deliberately offline: the retrieval filters and
guards are inspected directly, so a regression fails here long before it can
reach a generated answer.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.retrieval import faq_store
from app.retrieval.vector_store import version_filter
from app.species import species_applicable, species_in_text
from app.trust import (
    LEVEL_L1,
    LEVEL_L2,
    LEVEL_L3,
    LEVEL_L4,
    PENDING,
    REJECTED,
    VERIFIED,
    TrustProfile,
    applicability_conflict,
    evidence_eligible,
    is_strict_question,
)


def profile(level=LEVEL_L1, authority="official_technical", status=VERIFIED, **kw):
    return TrustProfile(
        level=level,
        authority=authority,
        verification_status=status,
        **kw,
    )


# --- L3 / L4 can never be evidence ----------------------------------------
@pytest.mark.parametrize("level", [LEVEL_L3, LEVEL_L4])
def test_third_party_qa_and_history_are_never_evidence(level):
    ok, reason = evidence_eligible(profile(level=level))
    assert not ok
    assert "never evidence" in reason


@pytest.mark.parametrize("level", [LEVEL_L3, LEVEL_L4])
def test_no_authority_can_rescue_a_low_trust_level(level):
    ok, _ = evidence_eligible(profile(level=level, authority="national_standard"))
    assert not ok


# --- review status ---------------------------------------------------------
def test_pending_faq_is_not_usable_as_evidence():
    ok, reason = evidence_eligible(profile(level=LEVEL_L2, status=PENDING))
    assert not ok
    assert "verification_status" in reason


def test_rejected_faq_is_not_usable_as_evidence():
    ok, reason = evidence_eligible(profile(level=LEVEL_L2, status=REJECTED))
    assert not ok


def test_superseded_document_is_not_usable():
    ok, reason = evidence_eligible(profile(superseded_by="abc"))
    assert not ok
    assert "superseded" in reason


def test_draft_standard_is_not_binding():
    ok, reason = evidence_eligible(profile(authority="standard_draft"))
    assert not ok
    assert "not binding" in reason


# --- strict topics ---------------------------------------------------------
def test_strict_topic_detection():
    assert is_strict_question("河蟹可以用恩诺沙星吗？")
    assert is_strict_question("休药期是多少天")
    assert not is_strict_question("河蟹的适宜水温是多少")


def test_strict_topic_rejects_unknown_authority():
    ok, reason = evidence_eligible(profile(authority="unknown"), strict=True)
    assert not ok
    assert "not binding" in reason or "strict question requires" in reason


def test_strict_topic_accepts_official_guidance():
    ok, _ = evidence_eligible(profile(authority="official_technical"), strict=True)
    assert ok


def test_strict_topic_accepts_binding_standard():
    ok, _ = evidence_eligible(profile(authority="national_standard"), strict=True)
    assert ok


# --- applicability ---------------------------------------------------------
def test_species_mismatch_is_a_conflict():
    conflict, reason = applicability_conflict(
        {"species": ["凡纳滨对虾"]}, {"species": ["中华绒螯蟹"]}
    )
    assert conflict
    assert "species mismatch" in reason


def test_general_applicability_never_conflicts():
    conflict, _ = applicability_conflict(
        {"species": ["通用"]}, {"species": ["中华绒螯蟹"]}
    )
    assert not conflict


def test_unstated_condition_is_not_a_conflict():
    conflict, _ = applicability_conflict({"species": ["凡纳滨对虾"]}, {})
    assert not conflict


def test_region_mismatch_is_a_conflict():
    conflict, reason = applicability_conflict({"region": "江苏省"}, {"region": "山东省"})
    assert conflict
    assert "region mismatch" in reason


# --- species applicability -------------------------------------------------
def test_cross_species_evidence_is_rejected():
    assert not species_applicable(["凡纳滨对虾"], {"鲤"})
    assert species_applicable(["凡纳滨对虾"], {"凡纳滨对虾"})
    assert species_applicable(["通用"], {"泥鳅"})
    assert species_applicable([], {"泥鳅"})


def test_species_detection_expanded_vocabulary():
    assert "泥鳅" in species_in_text("泥鳅养殖池水温过高怎么办")
    assert "鲤" in species_in_text("鲤春病毒血症的流行水温")
    assert "罗氏沼虾" in species_in_text("罗氏沼虾苗种培育密度")


# --- storage-level isolation ----------------------------------------------
def test_faq_filter_requires_verified_and_faq_source_type():
    flt = faq_store.faq_filter()
    conditions = {c.key: c for c in flt.must}
    assert conditions["source_type"].match.value == "faq"
    assert conditions["chunk_role"].match.value == "faq"
    assert conditions["verification_status"].match.value == "verified"


def test_document_filter_can_never_match_faq_points():
    """Document queries pin ``document_version_id``; FAQ points have none."""
    flt = version_filter([uuid.uuid4()])
    keys = {c.key for c in flt.must}
    assert "document_version_id" in keys
    # And FAQ points are stored with chunk_role="faq", not "child".
    roles = {c.key: c for c in flt.must}
    assert roles["chunk_role"].match.value == "child"


def test_upsert_refuses_unverified_faq():
    with pytest.raises(faq_store.UnverifiedFaqError):
        faq_store.upsert_faq(
            client=None,
            faq_id=uuid.uuid4(),
            payload={"verification_status": PENDING, "question": "q", "answer": "a"},
            dense=[0.0],
            sparse=None,
        )


def test_upsert_refuses_faq_without_status():
    with pytest.raises(faq_store.UnverifiedFaqError):
        faq_store.upsert_faq(
            client=None,
            faq_id=uuid.uuid4(),
            payload={"question": "q", "answer": "a"},
            dense=[0.0],
            sparse=None,
        )


# --- retrieval stage gating ------------------------------------------------
async def test_faq_stage_is_skipped_when_documents_are_sufficient_disabled(monkeypatch):
    """With the flag off, no FAQ lookup is even attempted."""
    from app.config import settings
    from app.retrieval import service

    called = {"search": 0}

    def fake_search(*args, **kwargs):
        called["search"] += 1
        return []

    monkeypatch.setattr(settings, "enable_faq_retrieval", False)
    monkeypatch.setattr(service, "search_faq", fake_search)
    evidence, trace = await service._supplement_with_faq(
        "河蟹的溶氧要求", None, SimpleNamespace(embed_query=lambda t: [0.0]), SimpleNamespace(query_vector=lambda t: None), [], "no_evidence"
    )
    assert evidence == []
    assert trace["skipped"] == "flag_disabled"
    assert called["search"] == 0


async def test_pending_faq_hit_is_rejected_at_retrieval(monkeypatch):
    """Even if a pending row somehow reached the index, retrieval drops it."""
    from app.config import settings
    from app.retrieval import service

    pending_hit = {
        "payload": {
            "faq_id": str(uuid.uuid4()),
            "question": "河蟹溶氧多少合适",
            "answer": "保持 1mg/L 即可",  # deliberately wrong
            "evidence_level": LEVEL_L2,
            "verification_status": PENDING,
            "source_authority": "official_technical",
            "supporting_version_ids": [str(uuid.uuid4())],
            "species": ["中华绒螯蟹"],
        },
        "score": 0.9,
        "dense_rank": 1,
        "sparse_rank": 1,
    }

    monkeypatch.setattr(settings, "enable_faq_retrieval", True)
    monkeypatch.setattr(service, "search_faq", lambda *a, **k: [pending_hit])
    monkeypatch.setattr(service, "get_client", lambda: SimpleNamespace(close=lambda: None))

    evidence, trace = await service._supplement_with_faq(
        "河蟹溶氧多少合适", None, SimpleNamespace(embed_query=lambda t: [0.0]), SimpleNamespace(query_vector=lambda t: None), [], "no_evidence"
    )
    assert evidence == []
    assert trace["rejected"][0]["reason"].startswith("verification_status")


async def test_faq_without_active_support_is_rejected(monkeypatch):
    from app.config import settings
    from app.retrieval import service

    hit = {
        "payload": {
            "faq_id": str(uuid.uuid4()),
            "question": "河蟹溶氧多少合适",
            "answer": "保持 5mg/L 以上",
            "evidence_level": LEVEL_L2,
            "verification_status": VERIFIED,
            "source_authority": "official_technical",
            "supporting_version_ids": [str(uuid.uuid4())],  # not active
            "species": ["中华绒螯蟹"],
        },
        "score": 0.9,
        "dense_rank": 1,
        "sparse_rank": 1,
    }
    monkeypatch.setattr(settings, "enable_faq_retrieval", True)
    monkeypatch.setattr(service, "search_faq", lambda *a, **k: [hit])
    monkeypatch.setattr(service, "get_client", lambda: SimpleNamespace(close=lambda: None))

    evidence, trace = await service._supplement_with_faq(
        "河蟹溶氧多少合适", None, SimpleNamespace(embed_query=lambda t: [0.0]), SimpleNamespace(query_vector=lambda t: None), [], "no_evidence"
    )
    assert evidence == []
    assert trace["rejected"][0]["reason"] == "support_not_active"


async def test_verified_faq_with_active_support_is_accepted(monkeypatch):
    from app.config import settings
    from app.retrieval import service

    version_id = uuid.uuid4()
    hit = {
        "payload": {
            "faq_id": str(uuid.uuid4()),
            "question": "河蟹溶氧多少合适",
            "answer": "养殖水体溶解氧应保持在 5mg/L 以上。",
            "evidence_level": LEVEL_L2,
            "verification_status": VERIFIED,
            "source_authority": "national_standard",
            "supporting_version_ids": [str(version_id)],
            "species": ["中华绒螯蟹"],
        },
        "score": 0.9,
        "dense_rank": 1,
        "sparse_rank": 1,
    }
    monkeypatch.setattr(settings, "enable_faq_retrieval", True)
    monkeypatch.setattr(service, "search_faq", lambda *a, **k: [hit])
    monkeypatch.setattr(service, "get_client", lambda: SimpleNamespace(close=lambda: None))

    evidence, trace = await service._supplement_with_faq(
        "河蟹溶氧多少合适",
        None,
        SimpleNamespace(embed_query=lambda t: [0.0]),
        SimpleNamespace(query_vector=lambda t: None),
        [version_id],
        "no_evidence",
    )
    assert len(evidence) == 1
    assert evidence[0].supplemental is True
    assert evidence[0].source_type == "faq"
    assert evidence[0].document_id is None
    assert trace["accepted"] == 1


async def test_faq_supplement_respects_cap(monkeypatch):
    from app.config import settings
    from app.retrieval import service

    version_id = uuid.uuid4()
    hits = [
        {
            "payload": {
                "faq_id": str(uuid.uuid4()),
                "question": f"河蟹溶氧 {i}",
                "answer": "溶解氧保持在 5mg/L 以上。",
                "evidence_level": LEVEL_L2,
                "verification_status": VERIFIED,
                "source_authority": "national_standard",
                "supporting_version_ids": [str(version_id)],
                "species": ["中华绒螯蟹"],
            },
            "score": 0.9 - i * 0.01,
            "dense_rank": i + 1,
            "sparse_rank": i + 1,
        }
        for i in range(5)
    ]
    monkeypatch.setattr(settings, "enable_faq_retrieval", True)
    monkeypatch.setattr(settings, "faq_supplement_k", 2)
    monkeypatch.setattr(service, "search_faq", lambda *a, **k: hits)
    monkeypatch.setattr(service, "get_client", lambda: SimpleNamespace(close=lambda: None))

    evidence, _ = await service._supplement_with_faq(
        "河蟹溶氧多少合适",
        None,
        SimpleNamespace(embed_query=lambda t: [0.0]),
        SimpleNamespace(query_vector=lambda t: None),
        [version_id],
        "no_evidence",
    )
    assert len(evidence) == 2

# --- faq_direct guards -----------------------------------------------------
def _direct_hit(**overrides):
    payload = {
        "faq_id": str(uuid.uuid4()),
        "question": "扣蟹培育池塘的溶氧量应保持在多少以上？",
        "answer": "溶氧量5mg/L以上，pH值7.5~8.5。",
        "evidence_level": LEVEL_L2,
        "verification_status": VERIFIED,
        "source_authority": "local_standard",
        "supporting_version_ids": [],
        "supporting_document_ids": [str(uuid.uuid4())],
        "species": ["中华绒螯蟹"],
    }
    payload.update(overrides.pop("payload", {}))
    hit = {"payload": payload, "score": 0.5, "dense_rank": 1, "sparse_rank": 1}
    hit.update(overrides)
    return hit


async def _run_direct(monkeypatch, hit, *, version_id=None, question="扣蟹培育池塘的溶氧量应保持在多少以上？", active=None):
    from app.config import settings
    from app.retrieval import direct as direct_module

    version_id = version_id or uuid.uuid4()
    hit["payload"]["supporting_version_ids"] = [str(version_id)]
    monkeypatch.setattr(settings, "enable_faq_retrieval", True)
    monkeypatch.setattr(settings, "enable_faq_direct_answer", True)
    monkeypatch.setattr(direct_module, "search_faq", lambda *a, **k: [hit])
    monkeypatch.setattr(direct_module, "get_client", lambda: SimpleNamespace(close=lambda: None))
    return await direct_module.try_faq_direct(
        question,
        None,
        SimpleNamespace(embed_query=lambda t: [0.0]),
        SimpleNamespace(query_vector=lambda t: None),
        active if active is not None else [version_id],
    )


async def test_faq_direct_accepts_clean_verified_answer(monkeypatch):
    answer, trace = await _run_direct(monkeypatch, _direct_hit())
    assert answer is not None
    assert trace["used"] is True
    assert answer.authority == "local_standard"


async def test_faq_direct_rejects_vector_only_match(monkeypatch):
    hit = _direct_hit()
    hit["sparse_rank"] = None
    answer, trace = await _run_direct(monkeypatch, hit)
    assert answer is None
    assert trace["fallback_reason"] == "not_top1_on_both_retrievers"


async def test_faq_direct_rejects_conditional_answer(monkeypatch):
    hit = _direct_hit(payload={"answer": "如果水温偏低则需要减少投喂，视情况调整。"})
    answer, trace = await _run_direct(monkeypatch, hit)
    assert answer is None
    assert trace["fallback_reason"] == "answer_is_conditional"


async def test_faq_direct_rejects_inactive_support(monkeypatch):
    # The FAQ claims support, but no version is active any more.
    answer, trace = await _run_direct(monkeypatch, _direct_hit(), active=[])
    assert answer is None
    assert trace["fallback_reason"] == "support_not_active"


async def test_faq_direct_rejects_species_mismatch(monkeypatch):
    from app.retrieval import direct as direct_module

    hit = _direct_hit(payload={"species": ["凡纳滨对虾"]})
    version_id = uuid.uuid4()
    hit["payload"]["supporting_version_ids"] = [str(version_id)]
    from app.config import settings

    monkeypatch.setattr(settings, "enable_faq_retrieval", True)
    monkeypatch.setattr(settings, "enable_faq_direct_answer", True)
    monkeypatch.setattr(direct_module, "search_faq", lambda *a, **k: [hit])
    monkeypatch.setattr(direct_module, "get_client", lambda: SimpleNamespace(close=lambda: None))

    ir = SimpleNamespace(species=["中华绒螯蟹"], growth_stage=[], region=None)
    answer, trace = await direct_module.try_faq_direct(
        "扣蟹培育池塘的溶氧量应保持在多少以上？",
        ir,
        SimpleNamespace(embed_query=lambda t: [0.0]),
        SimpleNamespace(query_vector=lambda t: None),
        [version_id],
    )
    assert answer is None
    assert "species mismatch" in trace["fallback_reason"]


async def test_faq_direct_disabled_by_default(monkeypatch):
    from app.config import settings
    from app.retrieval import direct as direct_module

    monkeypatch.setattr(settings, "enable_faq_direct_answer", False)
    answer, trace = await direct_module.try_faq_direct(
        "扣蟹培育池塘的溶氧量应保持在多少以上？", None, None, None, []
    )
    assert answer is None
    assert trace["fallback_reason"] == "faq_direct_disabled"


# --- parse quality (P0 sentence split / P1 boilerplate) --------------------
def test_english_sentences_split_without_cutting_words():
    from app.ingestion.chunker import _split_text

    text = (
        "The water depth should be 1.5 m for ponds. "
        "Next, add gypsum at 500 kg/ha to settle particles. "
        "Do not exceed 10% of stock."
    )
    chunks = _split_text(text, 60, 0)
    assert all(chunk[:1].isupper() or chunk[:1].isdigit() for chunk in chunks)
    assert any(chunk.startswith("Next, add gypsum") for chunk in chunks)
    assert not any("  " in chunk for chunk in chunks)


def test_html_boilerplate_is_dropped():
    from app.ingestion.html_parser import BOILERPLATE_MARKERS, HtmlParser

    parser = HtmlParser(base_url="http://example.org/a.htm")
    xml = (
        "<doc><p>欢迎您！来到全国水产技术推广总站、中国水产学会 • 首页• 组织机构</p>"
        "<h2>一、易发疾病</h2>"
        "<p>草鱼出血病：病原为草鱼呼肠孤病毒，水温20℃～30℃时易发病。</p>"
        "<p>主办单位：全国水产技术推广总站</p></doc>"
    )
    doc = parser.parse_xml(xml)
    texts = [block.text for block in doc.blocks]
    assert any("草鱼出血病" in text for text in texts)
    assert not any(any(marker in text for marker in BOILERPLATE_MARKERS) for text in texts)
