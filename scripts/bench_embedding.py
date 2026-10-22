#!/usr/bin/env python3
"""Reproducible BGE-M3 embedding benchmark on real chunks.

Samples chunks from the database (Chinese + English, short + long, multiple
sources), then measures load time, tokenisation and inference throughput for
several (dtype, batch_size, max_length) configurations.

Usage:
    uv run python ../../scripts/bench_embedding.py --sample 96
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402


def build_sample(limit: int):
    from app.db import SessionLocal
    from app.models import KbChunk, KbDocument

    async def run():
        async with SessionLocal() as db:
            rows = (await db.execute(
                select(KbChunk.content, KbDocument.source_type)
                .join(KbDocument, KbDocument.current_version_id == KbChunk.document_version_id)
                .where(KbDocument.status == "staging", KbChunk.chunk_role == "child")
            )).all()
        return [(r[0], r[1]) for r in rows if r[0]]

    items = asyncio.run(run())
    # deterministic spread across length buckets
    items.sort(key=lambda x: len(x[0]))
    step = max(1, len(items) // limit)
    picked = items[::step][:limit]
    return [text[:2000] for text, _ in picked]


def main() -> int:
    import torch
    from sentence_transformers import SentenceTransformer

    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=96)
    parser.add_argument("--model", default="BAAI/bge-m3")
    args = parser.parse_args()

    texts = build_sample(args.sample)
    lens = [len(t) for t in texts]
    print(f"sample={len(texts)} chars min={min(lens)} median={statistics.median(lens)} max={max(lens)}")
    print(f"mps_available={torch.backends.mps.is_available()}")

    configs = [
        ("fp32 bs8 ml1024", torch.float32, 8, 1024),
        ("fp16 bs32 ml512", torch.float16, 32, 512),
    ]
    for name, dtype, batch, max_len in configs:
        t0 = time.perf_counter()
        model = SentenceTransformer(args.model, device="mps", model_kwargs={"torch_dtype": dtype})
        model.max_seq_length = max_len
        load_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        batch_obj = model.tokenize(texts)
        tok_s = time.perf_counter() - t0
        tokens = int(batch_obj["input_ids"].numel())

        t0 = time.perf_counter()
        model.encode(texts, batch_size=batch, normalize_embeddings=True, show_progress_bar=False)
        inf_s = time.perf_counter() - t0

        print(
            f"{name}: load={load_s:.1f}s tokenize={tok_s:.2f}s infer={inf_s:.1f}s "
            f"chunks/s={len(texts)/inf_s:.1f} tokens/s={tokens/inf_s:.0f} "
            f"dtype={next(model.parameters()).dtype}"
        )
        del model
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
