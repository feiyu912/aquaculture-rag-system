"""Batch evaluation over the running chat API.

Ground truth is read from JSONL; this script never treats an LLM answer as
ground truth. Retrieval metrics are page-level proxies until chunk-level gold
labels are added.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


def read_cases(path: Path, limit: int | None) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    return cases[:limit] if limit else cases


def parse_sse(block: str) -> tuple[str, dict] | None:
    event = "message"
    data_lines: list[str] = []
    for line in block.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return None
    return event, json.loads("\n".join(data_lines))


async def run_case(
    client: httpx.AsyncClient,
    base_url: str,
    case: dict,
    mode: str,
) -> dict:
    body = {
        "question": case["question"],
        "retrieval_mode": mode,
        "species": case.get("species"),
        "category": case.get("category"),
    }
    started = time.perf_counter()
    sources: list[dict] = []
    answer = ""
    status: dict = {}
    citation: dict = {}
    done: dict = {}
    error = None
    async with client.stream("POST", f"{base_url}/api/chat/stream", json=body) as response:
        response.raise_for_status()
        buffer = ""
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                parsed = parse_sse(block)
                if not parsed:
                    continue
                event, payload = parsed
                if event == "status":
                    status = payload
                elif event == "sources":
                    sources = payload.get("sources") or []
                elif event == "token":
                    answer += payload.get("text") or ""
                elif event == "citation_check":
                    citation = payload
                elif event == "done":
                    done = payload
                elif event == "error":
                    error = payload
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    gold_pages = set(case.get("gold_pages") or [])
    gold_title = case.get("gold_title")
    hit_rank = None
    for rank, source in enumerate(sources, start=1):
        title_ok = not gold_title or source.get("title") == gold_title
        if title_ok and source.get("page") in gold_pages:
            hit_rank = rank
            break
    return {
        "id": case.get("id"),
        "question": case["question"],
        "mode": mode,
        "reference_answer": case.get("reference_answer"),
        "expect_insufficient": bool(case.get("expect_insufficient")),
        "answer": answer,
        "sources": sources,
        "status": status,
        "citation_check": citation,
        "done": done,
        "error": error,
        "elapsed_ms": elapsed_ms,
        "retrieval_hit": hit_rank is not None,
        "hit_rank": hit_rank,
        "mrr": (1.0 / hit_rank) if hit_rank else 0.0,
        "sufficient": bool(status.get("sufficient", True)),
        "source_count": len(sources),
        "cited_count": len(citation.get("cited_indices") or []),
        "citation_valid": bool(citation.get("valid", False)),
        "citation_coverage": float(citation.get("coverage") or 0.0),
        "ttft_ms": (done.get("timings") or {}).get("ttft_ms"),
        "total_ms": (done.get("timings") or {}).get("total_ms"),
        "cost_usd": done.get("cost_usd", 0.0),
    }


def summarize(rows: list[dict]) -> list[dict]:
    summary = []
    for mode in sorted({row["mode"] for row in rows}):
        subset = [row for row in rows if row["mode"] == mode]
        scored = [row for row in subset if not row["expect_insufficient"]]
        insufficient = [row for row in subset if row["expect_insufficient"]]
        summary.append(
            {
                "mode": mode,
                "cases": len(subset),
                "retrieval_hit_rate": round(
                    sum(row["retrieval_hit"] for row in scored) / len(scored), 3
                )
                if scored
                else 0.0,
                "mrr": round(statistics.mean([row["mrr"] for row in scored]), 3) if scored else 0.0,
                "citation_valid_rate": round(
                    sum(row["citation_valid"] for row in subset) / len(subset), 3
                ),
                "avg_citation_coverage": round(
                    statistics.mean([row["citation_coverage"] for row in subset]), 3
                ),
                "avg_sources": round(statistics.mean([row["source_count"] for row in subset]), 3),
                "refusal_rate": round(
                    sum(not row["sufficient"] for row in subset) / len(subset), 3
                ),
                "insufficient_expected_pass_rate": round(
                    sum(not row["sufficient"] for row in insufficient) / len(insufficient), 3
                )
                if insufficient
                else None,
                "avg_total_ms": round(statistics.mean([row["total_ms"] or 0 for row in subset]), 1),
                "avg_ttft_ms": round(statistics.mean([row["ttft_ms"] or 0 for row in subset]), 1),
                "total_cost_usd": round(sum(row["cost_usd"] or 0 for row in subset), 6),
            }
        )
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--modes", default="dense,bm25,hybrid,hybrid_rerank")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    cases = read_cases(args.dataset, args.limit)
    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=180.0) as client:
        for mode in modes:
            for case in cases:
                print(f"[{mode}] {case.get('id')} {case['question']}")
                rows.append(await run_case(client, args.base_url, case, mode))

    with (args.out / "results.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = summarize(rows)
    with (args.out / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)

    config = {
        "dataset": str(args.dataset),
        "modes": modes,
        "cases": len(cases),
        "created_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "note": "page-level retrieval proxy; support verification is not included",
    }
    (args.out / "run_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
