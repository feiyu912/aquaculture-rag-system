"""One evidence set for gating, generation, the sources event and citations.

The retrieval stage already budgets document evidence at ``max_sources`` and
appends at most ``faq_supplement_k`` verified FAQ items.  Chat used to truncate
the merged list with ``evidence[:max_sources]``; when five documents filled the
document budget, that dropped the FAQ items the sufficiency gate had just
counted, so the model saw less evidence than the gate did (and the sources
event described a different set again).

``finalize_evidence`` keeps the two budgets separate: FAQ never occupies a
document slot, and document overflow never removes an accepted FAQ.  It also
renumbers sources contiguously so the answer markers, sources event and
persisted citations all refer to the same indices.
"""

from __future__ import annotations

from app.retrieval.service import Evidence


def finalize_evidence(
    evidence: list[Evidence],
    *,
    document_slots: int,
    faq_slots: int,
) -> list[Evidence]:
    documents = [item for item in evidence if item.source_type != "faq"]
    faqs = [item for item in evidence if item.source_type == "faq"]
    keep = {id(item) for item in documents[:document_slots]}
    keep.update(id(item) for item in faqs[:faq_slots])
    selected = [item for item in evidence if id(item) in keep]
    for index, item in enumerate(selected, start=1):
        item.source_index = index
    return selected


def context_budget(
    evidence: list[Evidence], *, document_slots: int, faq_slots: int
) -> dict:
    faqs = sum(1 for item in evidence if item.source_type == "faq")
    documents = len(evidence) - faqs
    return {
        "document_slots": document_slots,
        "faq_slots": faq_slots,
        "documents_used": documents,
        "faq_used": faqs,
        "total_used": len(evidence),
        "within_budget": documents <= document_slots and faqs <= faq_slots,
    }
