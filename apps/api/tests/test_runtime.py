from __future__ import annotations

import threading
import time

import pytest

from app.runtime.mps_lock import exclusive_mps_lock


def test_file_lock_creates_file_and_releases(tmp_path):
    path = tmp_path / "mps.lock"
    with exclusive_mps_lock(str(path)):
        assert path.exists()
    with exclusive_mps_lock(str(path)):
        assert path.exists()


def test_file_lock_serializes_threads(tmp_path):
    path = tmp_path / "mps.lock"
    state = {"active": 0, "max_active": 0}
    guard = threading.Lock()

    def worker() -> None:
        with exclusive_mps_lock(str(path)):
            with guard:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            time.sleep(0.03)
            with guard:
                state["active"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert state["max_active"] == 1


def test_file_lock_does_not_swallow_body_errors(tmp_path):
    with pytest.raises(RuntimeError), exclusive_mps_lock(str(tmp_path / "mps.lock")):
        raise RuntimeError("inference failed")


def test_empty_path_is_noop(tmp_path):
    with exclusive_mps_lock(None):
        pass
    assert not list(tmp_path.iterdir())
