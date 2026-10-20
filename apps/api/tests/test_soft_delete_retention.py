from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.maintenance.cleanup import is_expired, retention_cutoff
from app.worker import effective_max_jobs, serial_inference_required

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def test_retention_cutoff_uses_configured_days():
    assert retention_cutoff(7, now=NOW) == NOW - timedelta(days=7)
    assert retention_cutoff(0, now=NOW) == NOW


def test_recent_soft_delete_is_retained():
    cutoff = retention_cutoff(7, now=NOW)
    assert not is_expired(NOW - timedelta(days=1), None, cutoff)


def test_expired_soft_delete_is_purgeable():
    cutoff = retention_cutoff(7, now=NOW)
    assert is_expired(NOW - timedelta(days=8), None, cutoff)


def test_legacy_row_without_deleted_at_falls_back_to_updated_at():
    cutoff = retention_cutoff(7, now=NOW)
    assert not is_expired(None, NOW - timedelta(days=2), cutoff)
    assert is_expired(None, NOW - timedelta(days=9), cutoff)


def test_naive_timestamp_is_treated_as_utc():
    cutoff = retention_cutoff(7, now=NOW)
    naive_recent = (NOW - timedelta(days=1)).replace(tzinfo=None)
    assert not is_expired(naive_recent, None, cutoff)


def test_missing_timestamp_is_expired():
    cutoff = retention_cutoff(7, now=NOW)
    assert is_expired(None, None, cutoff)


def test_mps_forces_single_job(monkeypatch):
    monkeypatch.setattr("app.worker.resolve_device", lambda value: "mps")
    assert serial_inference_required() is True
    assert effective_max_jobs() == 1


def test_cpu_allows_configured_concurrency(monkeypatch):
    from app.config import settings

    monkeypatch.setattr("app.worker.resolve_device", lambda value: "cpu")
    assert serial_inference_required() is False
    assert effective_max_jobs() == max(1, settings.worker_max_jobs)
