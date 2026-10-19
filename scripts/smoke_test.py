"""End-to-end A/B/C smoke test for the running API and ARQ worker.

A: upload -> answer with sources and a resolvable PDF page.
B: new version -> retrieval uses only the new version; rollback switches back.
C: out-of-domain question -> insufficient-evidence response, no citations.

Requires: docker compose services, uvicorn, arq worker.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
import pymupdf

ROOT = Path(__file__).resolve().parents[1]


def make_pdf(
    source: Path, pages: list[int], title: str, species: str, nonce: str, update: str | None = None
) -> Path:
    src = pymupdf.open(source)
    doc = pymupdf.open()
    for page in pages:
        doc.insert_pdf(src, from_page=page, to_page=page)
    src.close()
    doc.set_metadata(
        {
            "title": title,
            "author": "smoke-test",
            "subject": f"{species}-{nonce}",
            "keywords": species,
        }
    )
    if update:
        page = doc[0]
        page.insert_text(
            (48, 60),
            update,
            fontname="china-s",
            fontsize=10,
            color=(0.7, 0.05, 0.05),
        )
    target = Path("/tmp") / f"aqua_smoke_{nonce}_{pages[0]}_{'v2' if update else 'v1'}.pdf"
    doc.save(target, garbage=3, deflate=True)
    doc.close()
    return target


def parse_sse(block: str) -> tuple[str, dict] | None:
    event = "message"
    data: list[str] = []
    for line in block.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if not data:
        return None
    return event, json.loads("\n".join(data))


async def upload(
    client: httpx.AsyncClient,
    base: str,
    path: Path,
    title: str,
    species: str,
    category: str,
) -> dict:
    with path.open("rb") as handle:
        response = await client.post(
            f"{base}/api/documents",
            files={"file": (path.name, handle, "application/pdf")},
            data={"title": title, "species": species, "category": category},
        )
    response.raise_for_status()
    return response.json()


async def upload_version(
    client: httpx.AsyncClient, base: str, document_id: str, path: Path
) -> dict:
    with path.open("rb") as handle:
        response = await client.post(
            f"{base}/api/documents/{document_id}/versions",
            files={"file": (path.name, handle, "application/pdf")},
        )
    response.raise_for_status()
    return response.json()


async def poll_job(client: httpx.AsyncClient, base: str, job_id: str, timeout: float = 90) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = await client.get(f"{base}/api/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] in {"succeeded", "failed"}:
            return job
        await asyncio.sleep(0.5)
    raise TimeoutError(f"job {job_id} did not finish in {timeout}s")


async def chat(
    client: httpx.AsyncClient, base: str, question: str, mode: str, species: str | None
) -> dict:
    body = {"question": question, "retrieval_mode": mode, "species": species}
    result = {"answer": "", "sources": [], "status": {}, "citation": {}, "done": {}}
    async with client.stream("POST", f"{base}/api/chat/stream", json=body) as response:
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
                    result["status"] = payload
                elif event == "sources":
                    result["sources"] = payload.get("sources") or []
                elif event == "token":
                    result["answer"] += payload.get("text") or ""
                elif event == "citation_check":
                    result["citation"] = payload
                elif event == "done":
                    result["done"] = payload
    return result


async def delete_doc(client: httpx.AsyncClient, base: str, document_id: str) -> None:
    try:
        await client.delete(f"{base}/api/documents/{document_id}")
    except httpx.HTTPError as exc:
        print(f"cleanup failed for {document_id}: {exc}", file=sys.stderr)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--sample", type=Path, default=ROOT / "data/samples/aquaculture_sample.pdf")
    parser.add_argument(
        "--keep", action="store_true", help="keep created documents for manual demo"
    )
    args = parser.parse_args()

    if not args.sample.exists():
        print("sample PDF missing; run scripts/make_sample_pdf.py first", file=sys.stderr)
        return 2

    nonce = uuid.uuid4().hex[:8]
    general = make_pdf(args.sample, [0, 3], "水产养殖水质通用资料", "通用", nonce)
    crab = make_pdf(args.sample, [1], "中华绒螯蟹养殖示例资料", "中华绒螯蟹", nonce)
    crab_v2 = make_pdf(
        args.sample,
        [1],
        "中华绒螯蟹养殖示例资料",
        "中华绒螯蟹",
        nonce,
        update="本版本更新：蜕壳期溶解氧建议保持在 6 mg/L 以上。",
    )
    shrimp = make_pdf(args.sample, [2], "凡纳滨对虾养殖示例资料", "凡纳滨对虾", nonce)

    created: list[str] = []
    passed = 0
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            health = (await client.get(f"{args.base_url}/api/health")).json()
            assert health["status"] == "ok", f"health not ok: {health}"
            print("PASS health")

            general_job = await upload(
                client, args.base_url, general, "水产养殖水质通用资料", "通用", "水质管理"
            )
            crab_job = await upload(
                client, args.base_url, crab, "中华绒螯蟹养殖示例资料", "中华绒螯蟹", "养殖技术"
            )
            shrimp_job = await upload(
                client, args.base_url, shrimp, "凡纳滨对虾养殖示例资料", "凡纳滨对虾", "养殖技术"
            )
            created += [
                general_job["document_id"],
                crab_job["document_id"],
                shrimp_job["document_id"],
            ]
            for item in (general_job, crab_job, shrimp_job):
                job = await poll_job(client, args.base_url, item["job_id"])
                assert job["status"] == "succeeded", job
            print("PASS ingest (general + crab + shrimp)")

            for mode in ("dense", "bm25", "hybrid", "hybrid_rerank"):
                result = await chat(
                    client, args.base_url, "中华绒螯蟹养殖对溶解氧有什么要求？", mode, "中华绒螯蟹"
                )
                assert result["sources"], f"{mode}: no sources"
                assert all(
                    source["species"] in (["中华绒螯蟹"], ["通用"]) for source in result["sources"]
                ), f"{mode}: species leak"
                assert result["citation"]["valid"], f"{mode}: invalid citations"
                assert "不足" not in result["answer"], f"{mode}: wrongly refused"
                assert result["done"].get("retrieval_mode") == mode
            print("PASS four retrieval modes + species filter")

            first = result
            first_source = first["sources"][0]
            pdf = await client.get(
                f"{args.base_url}/api/documents/{first_source['document_id']}/file",
                params={"version_id": first_source["version_id"]},
            )
            assert pdf.status_code == 200 and pdf.headers["content-type"].startswith(
                "application/pdf"
            )
            print("PASS citation source resolves to PDF")

            version_job = await upload_version(
                client, args.base_url, crab_job["document_id"], crab_v2
            )
            version_status = await poll_job(client, args.base_url, version_job["job_id"])
            assert version_status["status"] == "succeeded", version_status
            detail = (
                await client.get(f"{args.base_url}/api/documents/{crab_job['document_id']}")
            ).json()
            assert detail["current_version_no"] == 2, detail
            after_update = await chat(
                client, args.base_url, "中华绒螯蟹养殖对溶解氧有什么要求？", "hybrid", "中华绒螯蟹"
            )
            crab_sources = [
                source
                for source in after_update["sources"]
                if source["document_id"] == crab_job["document_id"]
            ]
            assert crab_sources and all(source["version_no"] == 2 for source in crab_sources), (
                crab_sources
            )
            print("PASS version update activates v2 without old-version citations")

            rollback = await client.post(
                f"{args.base_url}/api/documents/{crab_job['document_id']}/rollback",
                json={"version_id": crab_job["version_id"]},
            )
            rollback.raise_for_status()
            assert rollback.json()["current_version_no"] == 1
            after_rollback = await chat(
                client, args.base_url, "中华绒螯蟹养殖对溶解氧有什么要求？", "hybrid", "中华绒螯蟹"
            )
            crab_sources = [
                source
                for source in after_rollback["sources"]
                if source["document_id"] == crab_job["document_id"]
            ]
            assert crab_sources and all(source["version_no"] == 1 for source in crab_sources), (
                crab_sources
            )
            print("PASS rollback switches retrieval back to v1")

            refusal = await chat(client, args.base_url, "今天上海天气怎么样？", "hybrid", None)
            assert refusal["status"].get("sufficient") is False, refusal["status"]
            assert not refusal["sources"], refusal["sources"]
            assert "不足" in refusal["answer"], refusal["answer"]
            assert not refusal["citation"].get("cited_indices"), refusal["citation"]
            print("PASS insufficient-evidence refusal")

            passed = 1
        finally:
            if not args.keep:
                for document_id in created:
                    await delete_doc(client, args.base_url, document_id)
            else:
                print("kept documents:", created)

    print("SMOKE TEST PASSED" if passed else "SMOKE TEST FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
