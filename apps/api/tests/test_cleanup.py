from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.api import documents
from app.worker import cleanup_deleted_vectors


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


def _db(version):
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(status="active", current_version_id=uuid.uuid4())
    db.execute.side_effect = [FakeResult([version]), FakeResult([])]
    return db


async def test_delete_enqueues_cleanup_after_commit():
    version = SimpleNamespace(id=uuid.uuid4(), status="ready")
    db = _db(version)
    pool = AsyncMock()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq_pool=pool)))

    await documents.delete_document(request, uuid.uuid4(), db)

    assert db.get.return_value.status == "deleted"
    assert db.get.return_value.current_version_id is None
    assert version.status == "archived"
    db.commit.assert_awaited_once()
    pool.enqueue_job.assert_awaited_once()
    assert pool.enqueue_job.await_args.args[0] == "cleanup_deleted_vectors"


async def test_delete_without_queue_still_succeeds():
    version = SimpleNamespace(id=uuid.uuid4(), status="ready")
    db = _db(version)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq_pool=None)))

    await documents.delete_document(request, uuid.uuid4(), db)

    assert db.get.return_value.status == "deleted"
    db.commit.assert_awaited_once()


async def test_worker_cleanup_uses_apply_mode(monkeypatch):
    calls = []

    async def fake_purge(*, apply: bool):
        calls.append(apply)
        return {"dry_run": not apply, "points_to_remove": 0}

    monkeypatch.setattr("app.worker.purge_deleted_vectors", fake_purge)
    result = await cleanup_deleted_vectors({})
    assert calls == [True]
    assert result["dry_run"] is False
