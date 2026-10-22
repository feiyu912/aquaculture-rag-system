from __future__ import annotations

from app.main import app


def test_documented_api_routes_are_mounted():
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/health",
        "/api/sessions",
        "/api/sessions/{session_id}",
        "/api/sessions/{session_id}/messages",
        "/api/chat/stream",
        "/api/messages/{message_id}/verify-claims",
        "/api/citations/{citation_id}/verify",
        "/api/documents",
        "/api/documents/{document_id}",
        "/api/documents/{document_id}/versions",
        "/api/documents/{document_id}/rollback",
        "/api/documents/{document_id}/file",
        "/api/documents/{document_id}/citations",
        "/api/species",
        "/api/jobs/{job_id}",
        "/api/jobs/{job_id}/retry",
        "/api/debug/query-logs/{request_id}",
        "/api/debug/stats",
        "/api/manage/documents",
        "/api/manage/documents/{document_id}",
        "/api/manage/documents/{document_id}/chunks",
        "/api/manage/stats",
        "/api/manage/facets",
        "/api/manage/jobs",
        "/api/manage/faq",
        "/api/manage/faq/{faq_id}",
        "/api/manage/capabilities",
        "/api/manage/llm",
    }
    assert expected - paths == set()
