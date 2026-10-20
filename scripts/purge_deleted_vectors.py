"""Dry-run/apply removal of Qdrant vectors for soft-deleted documents.

The database rows and original PDFs are deliberately kept: this only removes
derived Qdrant points that no active version can reference. Run without
``--apply`` first; the default is read-only. After ``--apply`` the active
manifest counts are refreshed automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.maintenance.cleanup import purge_deleted_vectors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually delete orphan points")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help="override SOFT_DELETE_RETENTION_DAYS; 0 purges immediately",
    )
    args = parser.parse_args()
    result = asyncio.run(
        purge_deleted_vectors(apply=args.apply, retention_days=args.retention_days)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
