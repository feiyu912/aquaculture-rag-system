"""V1a regression tests: isolation, payload contract, and main-chain safety.

Run: cd apps/api && uv run --with pytest python -m pytest ../../scripts/hf_qa/tests -q
"""

from __future__ import annotations

import json
import random
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings  # noqa: E402
from app.retrieval.vector_store import get_client  # noqa: E402

QA = ROOT / "data" / "hf_qa"
COLLECTION = "qa_memory_hf_v1"
PUNCT = "，。！？；：、（）【】《》“”‘’…—·,.!?;:()[]<>\"'`~ "


def normalize(text: str) -> str:
    v = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in v if ch not in PUNCT)


def trigrams(text: str) -> set[str]:
    v = normalize(text)
    return {v[i : i + 3] for i in range(len(v) - 2)} if len(v) >= 3 else ({v} if v else set())


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def test_collection_separate_and_counted():
    client = get_client()
    assert COLLECTION != settings.qdrant_collection
    assert client.collection_exists(COLLECTION)
    manifest = json.loads((QA / "qa_memory" / "manifest.json").read_text())
    count = client.count(collection_name=COLLECTION, exact=True).count
    assert count == manifest["final_points"] > 0


def test_payload_contract():
    client = get_client()
    points, _ = client.scroll(collection_name=COLLECTION, limit=50, with_payload=True)
    assert points
    for p in points:
        payload = p.payload or {}
        assert payload["source_type"] == "qa_memory"
        assert payload["evidence_level"] == "L0_unverified_qa"
        assert payload["verification_status"] == "unverified"
        assert payload["usage_scope"] == "hint_only"
        for field in ("question", "answer", "dataset_id", "revision", "original_id", "license"):
            assert payload.get(field), f"missing {field}"


def test_main_collection_has_no_qa_memory_points():
    client = get_client()
    from qdrant_client import models

    flt = models.Filter(must=[models.FieldCondition(key="source_type", match=models.MatchValue(value="qa_memory"))])
    assert client.count(collection_name=settings.qdrant_collection, count_filter=flt, exact=True).count == 0


def test_eval_set_disjoint_from_memory():
    eval_rows = load_jsonl(QA / "eval" / "eval_set_v1.jsonl")
    memory = load_jsonl(QA / "qa_memory" / "qa_memory_candidates.jsonl")
    mem_norm = {normalize(r["question"]) for r in memory}
    mem_tri = [trigrams(r["question"]) for r in memory]
    for r in eval_rows:
        assert normalize(r["question"]) not in mem_norm, f"exact leak: {r['question']}"
        tq = trigrams(r["question"])
        assert not any(jaccard(tq, t) >= 0.8 for t in mem_tri), f"near leak: {r['question']}"


def test_eval_set_disjoint_from_faq_snapshot():
    import csv

    eval_rows = load_jsonl(QA / "eval" / "eval_set_v1.jsonl")
    faq = list(csv.DictReader(open(QA / "external" / "faq_snapshot_20261021.csv", encoding="utf-8")))
    faq_tri = [trigrams(r["question"]) for r in faq]
    for r in eval_rows:
        tq = trigrams(r["question"])
        assert not any(jaccard(tq, t) >= 0.8 for t in faq_tri), f"faq leak: {r['question']}"


def test_eval_rows_have_document_evidence_only():
    eval_rows = load_jsonl(QA / "eval" / "eval_set_v1.jsonl")
    assert len(eval_rows) >= 200
    for r in eval_rows:
        assert r["reference_answer"]
        assert r["gold_evidence"], f"no gold evidence: {r['question']}"
        for g in r["gold_evidence"]:
            assert g["document_id"] and g["version_id"] and g["quote"]
        assert r["hf_reference_answer_unverified_diagnostic"] is not None


def test_chat_chain_does_not_reference_qa_memory():
    """The browse router may read the QA memory; the answering chain may not."""
    chain = [
        ROOT / "apps" / "api" / "app" / "api" / "chat.py",
        ROOT / "apps" / "api" / "app" / "api" / "sessions.py",
        ROOT / "apps" / "api" / "app" / "retrieval",
        ROOT / "apps" / "api" / "app" / "generation",
        ROOT / "apps" / "api" / "app" / "faq",
    ]
    offenders = []
    for target in chain:
        paths = [target] if target.is_file() else list(target.rglob("*.py"))
        for p in paths:
            text = p.read_text(encoding="utf-8")
            if "qa_memory" in text or "qa-library" in text or "qa_library" in text:
                offenders.append(str(p.relative_to(ROOT)))
    assert offenders == [], f"qa memory referenced by answering chain: {offenders}"