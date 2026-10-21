from __future__ import annotations

from app.retrieval.sufficiency import assess_evidence


def test_in_domain_question_passes_with_aggregate_evidence():
    result = assess_evidence(
        "中华绒螯蟹养殖对溶解氧有什么要求？",
        [
            "中华绒螯蟹喜欢水质清新、溶氧充足的环境。",
            "溶解氧：保持在 5 mg/L 以上，低氧时需及时增氧。",
        ],
    )
    assert result.sufficient
    assert result.matched_terms == ["中华绒螯蟹", "溶解氧"]


def test_out_of_domain_question_is_rejected():
    result = assess_evidence(
        "今天上海天气怎么样？",
        ["日常监测记录表中包含天气、水温和采样时间。"],
    )
    assert not result.sufficient
    assert result.reason == "weak_overlap"
    assert result.matched_terms == ["天气"]


def test_single_domain_term_is_valid():
    result = assess_evidence("溶解氧", ["溶解氧保持在 5 mg/L 以上。"])
    assert result.sufficient


def test_single_generic_term_is_not_valid():
    result = assess_evidence("天气", ["记录天气和水温。"])
    assert not result.sufficient


def test_abbreviation_matches_full_species_name():
    result = assess_evidence("对虾盐度要求", ["凡纳滨对虾养殖需要关注盐度。"])
    assert result.sufficient
    assert "对虾" in result.matched_terms


def test_no_evidence_fails():
    result = assess_evidence("溶解氧", [])
    assert not result.sufficient
    assert result.reason == "no_evidence"


def test_technical_nouns_split_by_jieba_still_pass_gate():
    result = assess_evidence(
        "环沟塘的沟宽和沟深有什么要求？",
        ["4.1池塘：环沟塘（回字型环沟）沟宽3m~4m，沟深60cm~80cm。"],
    )
    assert result.sufficient
    assert {"环沟", "沟宽", "沟深"} <= set(result.matched_terms)


def test_disease_spelling_alias_matches_gate():
    result = assess_evidence(
        "黑鳃病的症状和预防措施是什么？",
        ["黑腮病症状：鳃呈黄色、黑色；发病后用生石灰全池泼洒。"],
    )
    assert result.sufficient
    assert "黑鳃病" in result.matched_terms


def test_complete_drug_list_question_requires_a_declared_list():
    question = "水产养殖禁用渔药完整清单有哪些？"
    partial = "禁用渔药包括氯霉素、孔雀石绿等，使用时应严格执行休药期。"
    gate = assess_evidence(question, [partial])
    assert gate.sufficient is False
    assert gate.reason == "list_completeness_unverified"

    denied = "本标准未列出完整清单，仅给出部分示例：氯霉素、孔雀石绿。"
    assert assess_evidence(question, [denied]).sufficient is False

    declared = "禁用渔药清单如下：氯霉素、孔雀石绿、呋喃唑酮、硝基呋喃类。"
    assert assess_evidence(question, [declared]).sufficient is True


def test_completeness_guard_does_not_touch_ordinary_questions():
    gate = assess_evidence(
        "扣蟹培育池塘条件包括哪些方面？",
        ["扣蟹培育池塘应具备环沟、防逃墙、水草和独立的进排水系统。"],
    )
    assert gate.reason == "matched"
