#!/usr/bin/env python3
"""Stage 5 (V1a): build the HF QA memory dataset and its own Qdrant collection.

Inputs : processed/mxode_clean_pool.parquet (tier1 rows only), eval/eval_set_v1.jsonl
Outputs: qa_memory/qa_memory_candidates.jsonl, qa_memory/manifest.json,
         Qdrant collection qa_memory_hf_v1 (dense + bm25)

Isolation rules:
  * never writes to kb_chunks_* collections or the main PostgreSQL;
  * excludes the formal eval set by exact / 3-gram (J>=0.8) / embedding cosine
    (>=0.90) similarity;
  * payload marks every point L0_unverified_qa + usage_scope=hint_only, so
    downstream code cannot mistake it for citable evidence.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from qdrant_client import QdrantClient, models

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "hf_qa" / "processed"
OUTDIR = ROOT / "data" / "hf_qa" / "qa_memory"
EVAL = ROOT / "data" / "hf_qa" / "eval" / "eval_set_v1.jsonl"
COLLECTION = "qa_memory_hf_v1"
SEM_THRESHOLD = 0.90
EXACT_J = 0.80
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings  # noqa: E402
from app.ingestion.embedder import get_embedder  # noqa: E402
from app.retrieval.bm25 import BM25SparseEncoder  # noqa: E402
from app.retrieval.vector_store import get_client  # noqa: E402

from finalize import jaccard, normalize, trigrams  # noqa: E402


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    pool = [
        r
        for r in pq.read_table(PROC / "mxode_clean_pool.parquet").to_pylist()
        if r["tier"] == "tier1" and not (r.get("leak") or "")
    ]
    eval_rows = [json.loads(l) for l in open(EVAL, encoding="utf-8")]
    eval_q = [r["question"] for r in eval_rows]

    # lexical exclusions
    eval_norm = {normalize(q) for q in eval_q}
    eval_tri = [trigrams(q) for q in eval_q]
    kept, dropped_exact, dropped_near = [], 0, 0
    for r in pool:
        if normalize(r["question"]) in eval_norm:
            dropped_exact += 1
            continue
        tq = trigrams(r["question"])
        if any(jaccard(tq, te) >= EXACT_J for te in eval_tri):
            dropped_near += 1
            continue
        kept.append(r)
    print(f"pool tier1={len(pool)} exact_eval={dropped_exact} near_eval={dropped_near} kept={len(kept)}", flush=True)

    # semantic exclusion (bge-m3, MPS lock handled by the embedder)
    emb = get_embedder(settings.embedding_model, settings.qdrant_vector_size, settings.embedding_device,
                       settings.embedding_use_fp16, settings.embedding_batch_size, settings.embedding_max_length)
    eval_vecs = np.asarray(emb.embed_documents(eval_q), dtype=np.float32)
    eval_vecs /= np.linalg.norm(eval_vecs, axis=1, keepdims=True) + 1e-9
    mem_vecs = np.asarray(emb.embed_documents([r["question"] for r in kept]), dtype=np.float32)
    mem_vecs /= np.linalg.norm(mem_vecs, axis=1, keepdims=True) + 1e-9
    max_sim = (mem_vecs @ eval_vecs.T).max(axis=1)
    sim_keep = max_sim < SEM_THRESHOLD
    dropped_sem = int((~sim_keep).sum())
    kept = [r for r, ok in zip(kept, sim_keep) if ok]
    kept_vecs = mem_vecs[sim_keep]
    print(f"semantic exclusion (cos>={SEM_THRESHOLD}): dropped={dropped_sem} final={len(kept)}", flush=True)

    bm25 = BM25SparseEncoder(k1=settings.bm25_k1, b=settings.bm25_b, avg_len=settings.bm25_avg_len)
    client: QdrantClient = get_client()
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config={"dense": models.VectorParams(size=settings.qdrant_vector_size, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    ns = uuid.UUID("6f2c9a52-3a55-4c1e-9d0a-8b0f1c2d3e4f")
    points = []
    for r, vec in zip(kept, kept_vecs):
        pid = str(uuid.uuid5(ns, r["original_id"]))
        points.append(
            models.PointStruct(
                id=pid,
                vector={"dense": vec.tolist(), "bm25": bm25.document_vector(r["question"])},
                payload={
                    "source_type": "qa_memory",
                    "evidence_level": "L0_unverified_qa",
                    "verification_status": "unverified",
                    "usage_scope": "hint_only",
                    "dataset_id": r["dataset_id"],
                    "revision": r["revision"],
                    "original_id": r["original_id"],
                    "tier": r["tier"],
                    "topics": r["topics"],
                    "species": r["species_hits"],
                    "question": r["question"],
                    "answer": r["answer"],
                    "license": "CC-BY-SA-4.0",
                },
            )
        )
    for i in range(0, len(points), 64):
        client.upsert(collection_name=COLLECTION, points=points[i : i + 64], wait=(i + 64 >= len(points)))
    count = client.count(collection_name=COLLECTION, exact=True).count

    with open(OUTDIR / "qa_memory_candidates.jsonl", "w", encoding="utf-8") as f:
        for r in kept:
            f.write(
                json.dumps(
                    {
                        "original_id": r["original_id"],
                        "dataset_id": r["dataset_id"],
                        "revision": r["revision"],
                        "tier": r["tier"],
                        "question": r["question"],
                        "answer": r["answer"],
                        "topics": r["topics"],
                        "species_hits": r["species_hits"],
                        "license": "CC-BY-SA-4.0",
                        "evidence_level": "L0_unverified_qa",
                        "usage_scope": "hint_only",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    manifest = {
        "built_at": datetime.now(UTC).isoformat(),
        "collection": COLLECTION,
        "vectors": {"dense": settings.embedding_model, "bm25": bm25.config()},
        "source_pool_tier1": len(pool),
        "dropped_exact_eval": dropped_exact,
        "dropped_near_eval": dropped_near,
        "dropped_semantic_eval": dropped_sem,
        "semantic_threshold": SEM_THRESHOLD,
        "final_points": count,
        "payload_contract": {
            "source_type": "qa_memory",
            "evidence_level": "L0_unverified_qa",
            "verification_status": "unverified",
            "usage_scope": "hint_only",
        },
        "license": "CC-BY-SA-4.0 (attribution + share-alike if answers are redistributed)",
        "never": ["sources event", "sufficiency gate", "citation validation", "kb_chunks_* writes"],
    }
    (OUTDIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()