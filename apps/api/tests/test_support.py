from __future__ import annotations

from app.generation.support import verify_support


def test_support_accepts_close_lexical_overlap():
    result = verify_support("溶解氧应保持在 5 mg/L 以上。", "溶解氧：保持在 5 mg/L 以上。")
    assert result.status == "supported"
    assert result.method == "lexical_overlap_v0"


def test_support_rejects_unrelated_claim():
    result = verify_support("对虾适宜水温为 30 摄氏度。", "溶解氧保持在 5 mg/L 以上。")
    assert result.status == "unverified"
    assert result.score == 0.0
