"""Cross-process lock for MPS inference.

The in-process locks in the embedder/reranker serialize threads, but separate
uvicorn/ARQ processes can still submit Metal work concurrently.  On macOS this
can produce driver errors or out-of-memory failures.  A small advisory file
lock keeps model inference serialized within one host; it does not reduce model
memory because each process still owns a model instance.
"""

from __future__ import annotations

import fcntl
import logging
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


@contextmanager
def exclusive_mps_lock(path: str | None):
    """Acquire an exclusive advisory lock, or no-op when path is empty.

    The lock is deliberately best-effort: a read-only /tmp or a platform
    without ``fcntl`` should not make the API unusable.  The caller still has
    its in-process lock, and the limitation is logged.
    """
    if not path:
        yield
        return
    lock_path = Path(path)
    handle = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError as exc:
        # Do not silently pretend that cross-process safety was achieved.
        logger.warning("MPS cross-process lock unavailable (%s): %s", lock_path, exc)
        if handle is not None:
            handle.close()
        yield
        return
    try:
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
