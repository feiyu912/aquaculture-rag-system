from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api import chat, documents, health, sessions
from app.config import settings
from app.db import engine, init_db
from app.queue import create_arq_pool
from app.retrieval.vector_store import ensure_collection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.documents_path.mkdir(parents=True, exist_ok=True)
    settings.samples_path.mkdir(parents=True, exist_ok=True)
    await init_db()
    try:
        ensure_collection()
    except Exception as exc:
        logger.warning("Qdrant collection init failed: %s", exc)
    try:
        app.state.arq_pool = await create_arq_pool()
    except Exception as exc:
        app.state.arq_pool = None
        logger.warning("ARQ pool init failed: %s", exc)
    yield
    pool = getattr(app.state, "arq_pool", None)
    if pool is not None:
        await pool.aclose()
    await engine.dispose()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(sessions.router)
app.include_router(chat.router)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/demo", include_in_schema=False)
async def demo() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
