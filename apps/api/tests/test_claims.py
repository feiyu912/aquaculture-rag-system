from __future__ import annotations

from app.generation.claims import split_claims, summarize_claims, verify_claims


def test_split_claims_keeps_cited_table_rows_and_skips_meta():
    answer = """根据知识库中的资料，可以整理出以下信息：
- 溶解氧应保持在 5 mg/L 以上 [S1]。低氧时及时增氧 [S1]。
| 日期 | 溶解氧 |
| --- | --- |
| 2026-10-20 | 5 mg/L [S1] |
以上内容仅供参考。
"""
    claims = split_claims(answer)
    assert claims == [
        "溶解氧应保持在 5 mg/L 以上 [S1]。",
        "低氧时及时增氧 [S1]。",
        "2026-10-20 5 mg/L [S1]",
    ]


def test_table_cell_claims_are_checked_lexically():
    answer = """| 指标 | 适宜范围 |
| --- | --- |
| 水温 | 18 ℃~21 ℃ [S1] |
| pH | 6.5~8.5 [S1] |
"""
    claims = verify_claims(
        answer,
        [{"index": 1, "quote": "适宜水温为18 ℃~21 ℃。适宜pH为6.5~8.5。"}],
    )
    assert len(claims) == 2
    assert all(item["status"] == "supported" for item in claims)
    assert all(item["method"] == "lexical_overlap_v0" for item in claims)


def test_claim_without_citation_is_uncited():
    claims = verify_claims("这是一个没有引用的事实性陈述。", [])
    assert claims[0]["status"] == "uncited"
    assert claims[0]["cited_indices"] == []


def test_claim_support_is_lexical_v0():
    answer = "溶解氧应保持在 5 mg/L 以上 [S1]。"
    claims = verify_claims(
        answer,
        [{"index": 1, "quote": "溶解氧：保持在 5 mg/L 以上，低氧时及时增氧。"}],
    )
    assert claims[0]["status"] == "supported"
    assert claims[0]["method"] == "lexical_overlap_v0"
    assert claims[0]["cited_indices"] == [1]


def test_claim_with_unrelated_quote_is_unverified():
    claims = verify_claims(
        "对虾适宜水温为 30 摄氏度 [S1]。",
        [{"index": 1, "quote": "溶解氧保持在 5 mg/L 以上。"}],
    )
    assert claims[0]["status"] == "unverified"


def test_summary_counts_statuses():
    claims = [
        {"status": "supported"},
        {"status": "weak"},
        {"status": "uncited"},
    ]
    summary = summarize_claims(claims)
    assert summary["total"] == 3
    assert summary["supported"] == 1
    assert summary["unverified"] == 0
    assert summary["support_rate"] == 0.333
