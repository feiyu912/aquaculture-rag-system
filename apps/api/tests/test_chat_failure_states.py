from __future__ import annotations

import time
import uuid

import pytest

from app.api import chat
from app.models import ChatMessage


class _FakeMessage:
    status = "streaming"
    content = ""
    meta: dict = {}
    latency_ms = 0


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    async def get(self, model: object, ident: object) -> _FakeMessage:
        assert model is ChatMessage
        return _FakeMessage()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True


class _FakeSession:
    def __init__(self, db: _FakeDB) -> None:
        self.db = db

    async def __aenter__(self) -> _FakeDB:
        return self.db

    async def __aexit__(self, *args: object) -> bool:
        return False


class _Retrieval:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.active_versions = []


def _wire(monkeypatch: pytest.MonkeyPatch, db: _FakeDB) -> None:
    monkeypatch.setattr(chat, "SessionLocal", lambda: _FakeSession(db))


async def test_persist_failure_without_retrieval_does_not_raise(monkeypatch):
    """The pre-fix code raised AttributeError on retrieval.config and left the
    assistant row in 'streaming'; a failed retrieval must persist 'failed'."""
    db = _FakeDB()
    _wire(monkeypatch, db)
    message_id = uuid.uuid4()

    await chat._persist_failure(
        message_id,
        "req-1",
        "q",
        "",
        "retrieval_failed: qdrant down",
        time.perf_counter(),
        uuid.uuid4(),
    )

    assert db.committed is True
    log = db.added[0]
    assert log.route == "rag"
    assert log.retrieval_config == {}
    assert log.citation_check["error"].startswith("retrieval_failed")


async def test_persist_failure_keeps_retrieval_route_when_present(monkeypatch):
    db = _FakeDB()
    _wire(monkeypatch, db)

    await chat._persist_failure(
        uuid.uuid4(),
        "req-2",
        "q",
        "partial",
        "generation_failed: timeout",
        time.perf_counter(),
        uuid.uuid4(),
        _Retrieval({"adaptive_route": "graph_augmented"}),
    )

    assert db.added[0].route == "graph_augmented"


async def test_persist_failure_swallows_db_errors(monkeypatch):
    class _BrokenSession:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(chat, "SessionLocal", lambda: _BrokenSession())

    # A second failure while persisting must not replace the original error.
    await chat._persist_failure(
        uuid.uuid4(),
        "req-3",
        "q",
        "",
        "retrieval_failed: qdrant down",
        time.perf_counter(),
        uuid.uuid4(),
    )