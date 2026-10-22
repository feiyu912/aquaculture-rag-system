"""End-to-end verification of the read-only management API on a throwaway DB.

Creates a temporary PostgreSQL database, seeds >100 documents with the exact
edge cases the management UI must distinguish (active/staging/failed/deleted,
draft vs binding standard, duplicates, multi-version, HTML/PDF, FAQ support),
exercises the ASGI endpoints, then drops the database.

It never touches the real knowledge base and never calls an LLM/Qdrant write.
Run from ``apps/api``:

    uv run python scripts/verify_management_api.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE_PG = os.environ.get(
    "VERIFY_PG_URL", "postgresql://aquaculture:aquaculture@127.0.0.1:5432/postgres"
)
DB_NAME = f"aqua_manage_verify_{uuid.uuid4().hex[:10]}"


def sqlalchemy_url(database: str) -> str:
    return BASE_PG.replace("postgresql://", "postgresql+asyncpg://").rsplit("/", 1)[0] + f"/{database}"


async def create_database() -> None:
    conn = await asyncpg.connect(BASE_PG)
    try:
        await conn.execute(f'CREATE DATABASE "{DB_NAME}"')
    finally:
        await conn.close()


async def drop_database() -> None:
    conn = await asyncpg.connect(BASE_PG)
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1",
            DB_NAME,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}"')
    finally:
        await conn.close()


async def seed() -> dict:
    from app.db import SessionLocal
    from app.models import (
        ChatCitation,
        ChatMessage,
        ChatSession,
        FaqEntry,
        KbChunk,
        KbDocument,
        KbDocumentVersion,
        KbIngestJob,
    )

    ids: dict[str, object] = {}
    async with SessionLocal() as db:
        doc_rows: list[KbDocument] = []
        version_rows: list[KbDocumentVersion] = []
        chunk_rows: list[KbChunk] = []
        job_rows: list[KbIngestJob] = []

        def add_version(doc: KbDocument, version_no: int, status: str) -> KbDocumentVersion:
            version = KbDocumentVersion(
                id=uuid.uuid4(),
                document_id=doc.id,
                version_no=version_no,
                content_hash=f"{doc.id.hex}{version_no}".ljust(64, "0")[:64],
                file_path=f"/tmp/{doc.id}-v{version_no}.pdf",
                file_size=100,
                page_count=3,
                status=status,
                parser_name="test",
                parser_version="1",
            )
            version_rows.append(version)
            return version

        def add_chunks(version: KbDocumentVersion, count: int = 2) -> None:
            parent = KbChunk(
                id=uuid.uuid4(),
                document_version_id=version.id,
                parent_id=None,
                chunk_role="parent",
                ordinal=0,
                content="父块内容",
                content_hash=f"p{version.id}"[:64],
                heading_path=["测试"],
                page_from=1,
                page_to=1,
                token_count=10,
                locations=[],
            )
            chunk_rows.append(parent)
            for index in range(count):
                chunk_rows.append(
                    KbChunk(
                        id=uuid.uuid4(),
                        document_version_id=version.id,
                        parent_id=parent.id,
                        chunk_role="child",
                        ordinal=index,
                        content=f"子块内容 {index}",
                        content_hash=f"c{version.id}{index}"[:64],
                        heading_path=["测试"],
                        page_from=1,
                        page_to=1,
                        token_count=10,
                        locations=[],
                    )
                )

        for index in range(120):
            if index < 60:
                status = "active"
                verification = "verified" if index < 50 else "pending"
            elif index < 100:
                status = "staging"
                verification = "pending"
            else:
                status = "deleted"
                verification = "pending"

            authority = [
                "national_standard",
                "standard_draft",
                "official_technical",
                "peer_reviewed",
                "synthetic",
            ][index % 5]
            meta = {
                "language": "zh" if index % 2 == 0 else "en",
                "license": "CC-BY" if index % 3 else None,
                "source_id": f"src-{index:03d}",
            }
            if index == 45:
                authority = "local_standard"
                meta["document_status"] = "draft"
            source_url = (
                "https://dup.example/shared.pdf"
                if index < 5 and status == "active"
                else f"https://example.org/doc-{index}.pdf"
            )
            doc = KbDocument(
                id=uuid.uuid4(),
                title=f"测试资料 {index:03d} 南美白对虾" if index % 3 else f"测试资料 {index:03d} 草鱼",
                category="养殖技术" if index % 2 else "病害防控",
                species=["凡纳滨对虾"] if index % 3 else ["草鱼"],
                source_org="测试机构",
                source_url=source_url,
                publish_year=2020 + (index % 5),
                status=status,
                doc_metadata=meta,
                source_type=(
                    "web"
                    if index == 89
                    else ("html" if index % 10 == 0 else "pdf")
                ),
                authority_level=authority,
                verification_status=verification,
                technical_review_status="warn" if index % 7 == 0 else "pass",
                domain_review_status="pending",
                review_flags=["heading_pollution x2"] if index % 7 == 0 else [],
            )
            doc_rows.append(doc)
            if status == "deleted":
                continue

            if status == "staging" and index >= 90:
                if index == 99:
                    # A retry that failed before ever producing a current
                    # version must surface as "failed", not "staging".
                    failed_version = add_version(doc, 0, "failed")
                    job_rows.append(
                        KbIngestJob(
                            document_version_id=failed_version.id,
                            job_type="ingest",
                            status="failed",
                            attempts=2,
                            progress=30,
                            current_stage="parse",
                            error_code="ParserError",
                            error_message="测试失败",
                            idempotency_key=f"job-{doc.id}",
                        )
                    )
                continue

            if index < 3:
                archived = add_version(doc, 0, "archived")
                doc.current_version_id = None
                current = add_version(doc, 1, "ready")
                doc.current_version_id = current.id
                add_chunks(archived)
            else:
                current = add_version(doc, 0, "ready")
                doc.current_version_id = current.id
                if index == 4:
                    # Newer failed attempt must not make the ready current
                    # version look unavailable in the library stats.
                    add_version(doc, 2, "failed")
            add_chunks(current)

        db.add_all(doc_rows)
        await db.flush()
        db.add_all(version_rows)
        await db.flush()
        db.add_all(chunk_rows)
        await db.flush()
        active_version_id = next(
            doc.current_version_id
            for doc in doc_rows
            if doc.status == "active" and doc.source_type == "pdf"
        )
        job_rows.append(
            KbIngestJob(
                document_version_id=active_version_id,
                job_type="ingest",
                status="succeeded",
                attempts=1,
                progress=100,
                current_stage="done",
                idempotency_key="job-active",
            )
        )
        db.add_all(job_rows)
        await db.flush()

        # Source-citation fixtures: an active PDF, a deleted doc and a FAQ with
        # one active support plus one FAQ whose only support is gone.
        active_doc = next(
            doc
            for doc in doc_rows
            if doc.status == "active" and doc.current_version_id and doc.source_type == "pdf"
        )
        active_version = next(v for v in version_rows if v.id == active_doc.current_version_id)
        deleted_doc = next(doc for doc in doc_rows if doc.status == "deleted")

        session = ChatSession(title="管理 API 验证会话")
        db.add(session)
        await db.flush()
        user = ChatMessage(session_id=session.id, role="user", content="测试问题")
        assistant = ChatMessage(
            session_id=session.id,
            role="assistant",
            content="测试回答 [S1][S2][S3][S4]",
            status="completed",
            meta={},
        )
        db.add_all([user, assistant])
        await db.flush()

        now = datetime.now(UTC)
        faq_ok = FaqEntry(
            question="测试 FAQ 有有效支撑",
            answer="测试答案",
            question_norm="测试解答",
            question_hash="f" * 64,
            species=["凡纳滨对虾"],
            supporting=[
                {
                    "document_id": str(active_doc.id),
                    "version_id": str(active_version.id),
                    "page": 1,
                    "quote": "测试引文",
                }
            ],
            evidence_status="supported",
            review_status="verified",
            usage_scope="knowledge",
            reviewer="tester",
            reviewed_at=now,
            content_hash="e" * 64,
            indexed_at=now,
            source_dataset="test",
            original_source_url="https://example.org/faq-source",
        )
        faq_broken = FaqEntry(
            question="测试 FAQ 支撑已失效",
            answer="测试答案 2",
            question_norm="测试答案二",
            question_hash="d" * 64,
            species=["草鱼"],
            supporting=[
                {
                    "document_id": str(deleted_doc.id),
                    "version_id": str(uuid.uuid4()),
                    "page": 1,
                    "quote": "失效引文",
                }
            ],
            evidence_status="supported",
            review_status="verified",
            usage_scope="knowledge",
            reviewer="tester",
            reviewed_at=now,
            content_hash="c" * 64,
            source_dataset="test",
        )
        db.add_all([faq_ok, faq_broken])
        await db.flush()

        citations = [
            ChatCitation(
                message_id=assistant.id,
                source_index=1,
                document_id=active_doc.id,
                document_version_id=active_version.id,
                source_type="document",
                quote="正常原文",
                page=1,
                bbox={
                    "page": 1,
                    "bbox": [1, 2, 3, 4],
                    "locations": [
                        {"page": 1, "bbox": [1, 2, 3, 4]},
                        {"page": 3, "bbox": [5, 6, 7, 8]},
                    ],
                },
                support_status="supported",
            ),
            ChatCitation(
                message_id=assistant.id,
                source_index=2,
                document_id=deleted_doc.id,
                document_version_id=None,
                source_type="document",
                quote="已删除原文",
                page=1,
                support_status="unverified",
            ),
            ChatCitation(
                message_id=assistant.id,
                source_index=3,
                document_id=None,
                document_version_id=None,
                source_type="faq",
                faq_id=faq_ok.id,
                quote="有效 FAQ",
                page=None,
                support_status="supported",
            ),
            ChatCitation(
                message_id=assistant.id,
                source_index=4,
                document_id=None,
                document_version_id=None,
                source_type="faq",
                faq_id=faq_broken.id,
                quote="失效 FAQ",
                page=None,
                support_status="supported",
            ),
        ]
        db.add_all(citations)
        await db.commit()
        ids.update(
            session_id=session.id,
            faq_ok=faq_ok.id,
            faq_broken=faq_broken.id,
            deleted_doc=deleted_doc.id,
            active_version=active_version.id,
            active_doc=active_doc.id,
        )
    return ids


async def main() -> int:
    await create_database()
    os.environ["DATABASE_URL"] = sqlalchemy_url(DB_NAME)
    os.environ["AUTO_CREATE_TABLES"] = "true"
    os.environ["QDRANT_COLLECTION"] = "verify_management_api_unused"

    # Import after DATABASE_URL is set: app.config reads it at import time.
    from httpx import ASGITransport, AsyncClient

    from app.api import manage
    from app.db import engine, init_db
    from app.main import app

    async def no_qdrant():
        return None, "skipped in isolated verification"

    manage._faq_index_points = no_qdrant  # type: ignore[attr-defined]
    await init_db()
    try:
        ids = await seed()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async def get(path: str):
                response = await client.get(path)
                assert response.status_code == 200, (path, response.status_code, response.text[:400])
                return response.json()

            page1 = await get("/api/manage/documents?limit=25&offset=0&sort=created_desc")
            page2 = await get("/api/manage/documents?limit=25&offset=25&sort=created_desc")
            assert page1["total"] == 100, page1["total"]
            assert page1["pages"] == 4
            assert len(page1["items"]) == len(page2["items"]) == 25
            assert not ({item["id"] for item in page1["items"]} & {item["id"] for item in page2["items"]})
            assert all(item["status"] != "deleted" for item in page1["items"])

            assert (await get("/api/manage/documents?status=active&limit=100"))["total"] == 60
            staging_page = await get("/api/manage/documents?status=staging&limit=100")
            assert staging_page["total"] == 39, (staging_page["total"], [i["status"] for i in staging_page["items"]][:5])
            assert any(item["current_version_id"] is None for item in staging_page["items"])
            failed_page = await get("/api/manage/documents?status=failed&limit=100")
            assert failed_page["total"] == 1
            assert failed_page["items"][0]["status"] == "failed"
            failed_detail = await get(
                f"/api/manage/documents/{failed_page['items'][0]['id']}"
            )
            assert failed_detail["status"] == "failed"
            assert failed_detail["current_version_id"] is None
            failed_jobs = await get(
                f"/api/manage/jobs?document_id={failed_detail['id']}"
            )
            assert failed_jobs["total"] == 1, failed_jobs["total"]
            assert failed_jobs["items"][0]["status"] == "failed"
            assert failed_jobs["items"][0]["error_code"] == "ParserError"
            assert (await get("/api/manage/documents?status=deleted&limit=100"))["total"] == 20
            assert (await get("/api/manage/documents?status=staging&published=true"))["total"] == 0
            assert (await get("/api/manage/documents?published=true&limit=100"))["total"] == 50
            assert (await get("/api/manage/documents?technical_review=warn&limit=100"))["total"] == 15
            assert (await get("/api/manage/documents?document_type=standard_draft&limit=100"))["total"] == 21
            assert (await get("/api/manage/documents?document_type=standard&limit=100"))["total"] == 19
            assert (await get("/api/manage/documents?q=南美白对虾&limit=100"))["total"] > 0
            html_page = await get("/api/manage/documents?source_type=html&limit=100")
            assert html_page["total"] == 11
            assert all(item["source_type"] == "html" for item in html_page["items"])

            stats = await get("/api/manage/stats")
            assert stats["documents"]["total"] == 100
            assert stats["documents"]["records_including_deleted"] == 120
            assert stats["documents"]["by_verification"].get("verified") == 50, stats["documents"][
                "by_verification"
            ]
            assert stats["documents"]["retrievable"] == 50
            assert stats["documents"]["failed"] == 1
            assert stats["documents"]["by_status"]["failed"] == 1
            assert stats["documents"]["by_status"]["staging"] == 39
            assert stats["documents"]["independent_sources"]["effective"] == 46
            assert stats["documents"]["independent_sources"]["duplicate_or_repeated_records"] == 4
            assert stats["versions"]["documents_with_multiple_versions"] == 4
            assert stats["versions"]["by_status"].get("failed") == 2
            assert stats["chunks"]["all_versions"]["total"] == 279

            facets = await get("/api/manage/facets?include_deleted=true")
            assert sum(item["count"] for item in facets["status"]) == 120
            assert sum(item["count"] for item in facets["document_type"]) == 100
            assert {item["value"] for item in facets["status"]} == {"active", "staging", "failed", "deleted"}

            active_page = await get("/api/manage/documents?status=active&limit=1")
            detail = await get(f"/api/manage/documents/{active_page['items'][0]['id']}")
            assert detail["versions"], detail["versions"]
            assert detail["review_flag_details"] is not None
            assert detail["storage"]["policy"] in {"local_pdf", "html_snapshot"}

            version_citations = await get(
                f"/api/documents/{ids['active_doc']}/citations?version_id={ids['active_version']}"
            )
            assert len(version_citations) == 1
            assert version_citations[0]["document_version_id"] == str(ids["active_version"])
            assert version_citations[0]["page"] == 1
            assert version_citations[0]["page_end"] == 3
            assert [item["page"] for item in version_citations[0]["locations"]] == [1, 3]
            assert (
                await get(
                    f"/api/documents/{ids['active_doc']}/citations?version_id={uuid.uuid4()}"
                )
                == []
            )

            messages = await get(f"/api/sessions/{ids['session_id']}/messages")
            citations = {citation["source_index"]: citation for citation in messages[1]["citations"]}
            assert citations[1]["available"] is True
            assert citations[1]["media_type"] == "pdf"
            assert citations[2]["available"] is False
            assert citations[2]["unavailable_reason"] == "document_deleted"
            assert citations[3]["source_type"] == "faq"
            assert citations[3]["media_type"] == "faq"
            assert citations[3]["available"] is True
            assert citations[3]["document_id"] is None and citations[3]["page"] is None
            assert citations[4]["available"] is False
            assert citations[4]["unavailable_reason"] == "faq_support_invalid"

            faq = await get(f"/api/manage/faq/{ids['faq_ok']}")
            assert faq["review_provenance"] == "human_recorded"
            assert faq["supporting"][0]["available"] is True
            unindexed = await get("/api/manage/faq?indexed=false&limit=100")
            assert any(item["id"] == str(ids["faq_broken"]) for item in unindexed["items"])

        print(
            "PASS management API: 100 live / 20 deleted, pages=4, "
            "effective=46, FAQ+document citation availability"
        )
        return 0
    finally:
        await engine.dispose()
        await drop_database()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise
