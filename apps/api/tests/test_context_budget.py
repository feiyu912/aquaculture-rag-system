from __future__ import annotations

import uuid

from app.generation.context import context_budget, finalize_evidence
from app.generation.llm import build_evidence_block
from app.media import citation_locations
from app.retrieval.service import Evidence


def evidence(index: int, *, source_type: str = "document", media_type: str = "pdf") -> Evidence:
    return Evidence(
        source_index=index,
        document_id=uuid.uuid4() if source_type == "document" else None,
        version_id=uuid.uuid4() if source_type == "document" else None,
        parent_chunk_id=uuid.uuid4() if source_type == "document" else None,
        child_chunk_id=uuid.uuid4() if source_type == "document" else None,
        title=f"source-{source_type}-{index}",
        version_no=1 if source_type == "document" else 0,
        page=1 if media_type == "pdf" else None,
        quote="quote",
        content="content",
        location=None,
        score=0.5,
        source_type=source_type,
        media_type=media_type,
    )


def test_faq_appended_after_five_documents_survives_the_context_budget():
    docs = [evidence(i) for i in range(1, 6)]
    faqs = [evidence(6, source_type="faq", media_type="faq"), evidence(7, source_type="faq", media_type="faq")]
    merged = [*docs, *faqs]

    selected = finalize_evidence(merged, document_slots=5, faq_slots=2)

    assert len(selected) == 7
    assert [item.source_type for item in selected] == ["document"] * 5 + ["faq"] * 2
    assert [item.source_index for item in selected] == list(range(1, 8))
    budget = context_budget(selected, document_slots=5, faq_slots=2)
    assert budget["faq_used"] == 2
    assert budget["within_budget"] is True
    # The generation prompt must see the FAQ slots too; trimming the list is
    # not enough if the prompt builder silently re-caps it.
    block = build_evidence_block(selected)
    assert 'id="S6"' in block and 'id="S7"' in block


def test_extra_documents_are_trimmed_but_faq_is_not_dropped():
    docs = [evidence(i) for i in range(1, 8)]
    faqs = [evidence(8, source_type="faq", media_type="faq")]
    selected = finalize_evidence([*docs, *faqs], document_slots=5, faq_slots=2)
    assert len(selected) == 6
    assert [item.source_type for item in selected[-1:]] == ["faq"]
    assert [item.source_index for item in selected] == [1, 2, 3, 4, 5, 6]


def test_faq_never_consumes_a_document_slot():
    docs = [evidence(1)]
    faqs = [evidence(2, source_type="faq", media_type="faq")]
    selected = finalize_evidence([*docs, *faqs], document_slots=1, faq_slots=0)
    assert [item.source_type for item in selected] == ["document"]


def test_source_payload_marks_html_and_faq_without_fake_pdf_fields():
    html = evidence(1, media_type="html")
    html.page = 2  # a stray page number must not be presented as a PDF page
    html.source_url = "https://example.org/page.html"
    html.location = {"coordinate_system": "html", "paragraph": 3}
    html_source = html.as_source()
    assert html_source["media_type"] == "html"
    assert html_source["source_type"] == "document"
    assert html_source["page"] is None
    assert html_source["bbox"] is None
    assert html_source["location"]["coordinate_system"] == "html"

    legacy_web = evidence(3, media_type="web")
    legacy_web.page = 4
    web_source = legacy_web.as_source()
    assert web_source["media_type"] == "html"
    assert web_source["page"] is None
    assert web_source["bbox"] is None

    faq = evidence(2, source_type="faq", media_type="faq")
    faq.faq_id = uuid.uuid4()
    faq_source = faq.as_source()
    assert faq_source["source_type"] == "faq"
    assert faq_source["media_type"] == "faq"
    assert faq_source["document_id"] is None
    assert faq_source["version_id"] is None
    assert faq_source["page"] is None
    assert faq_source["location"] is None


def test_historical_location_blob_keeps_html_anchor_without_pdf_fields():
    locations = citation_locations(
        {
            "coordinate_system": "html",
            "paragraph": 3,
            "page": 1,
            "bbox": [1, 2, 3, 4],
            "locations": [
                {
                    "coordinate_system": "html",
                    "paragraph": 3,
                    "page": 1,
                    "bbox": [1, 2, 3, 4],
                }
            ],
        },
        "html",
    )
    assert len(locations) == 1
    assert locations[0]["paragraph"] == 3
    assert "page" not in locations[0]
    assert "bbox" not in locations[0]
    assert citation_locations({"page": 1, "bbox": [1, 2, 3, 4]}, "faq") == []
