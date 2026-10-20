from __future__ import annotations

import uuid

from app.retrieval.service import Evidence


def test_source_exposes_bbox_and_stable_ids():
    doc_id = uuid.uuid4()
    version_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    evidence = Evidence(
        source_index=1,
        document_id=doc_id,
        version_id=version_id,
        parent_chunk_id=parent_id,
        child_chunk_id=child_id,
        title="测试规程",
        version_no=2,
        page=7,
        quote="溶氧量5mg/L以上",
        content="溶氧量5mg/L以上，pH值7.5~8.5",
        location={
            "page": 7,
            "bbox": [70.9, 170.0, 543.8, 213.4],
            "coordinate_system": "pdf_points",
            "origin": "bottom-left",
            "rotation": 0,
            "page_width": 595.3,
            "page_height": 841.9,
        },
        score=0.9,
        species=["中华绒螯蟹"],
        heading_path=["8.1水质指标"],
    )
    source = evidence.as_source()
    assert source["source_id"] == "S1"
    assert source["document_id"] == str(doc_id)
    assert source["version_id"] == str(version_id)
    assert source["chunk_id"] == str(parent_id)
    assert source["child_chunk_id"] == str(child_id)
    assert source["bbox"] == [70.9, 170.0, 543.8, 213.4]
    assert source["page_height"] == 841.9
    assert source["location"]["origin"] == "bottom-left"


def test_source_without_location_is_null_safe():
    evidence = Evidence(
        source_index=1,
        document_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        parent_chunk_id=uuid.uuid4(),
        child_chunk_id=uuid.uuid4(),
        title="无坐标",
        version_no=1,
        page=1,
        quote="文本",
        content="文本",
        location=None,
        score=0.1,
    )
    source = evidence.as_source()
    assert source["bbox"] is None
    assert source["location"] is None
