"""Create tables and apply additive schema migrations."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.db import engine, init_db


async def main() -> None:
    await init_db()
    await engine.dispose()
    print("database schema is up to date")


if __name__ == "__main__":
    asyncio.run(main())
