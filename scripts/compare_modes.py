import json
import statistics
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
MODES = ["dense", "bm25", "hybrid", "hybrid_rerank"]
QUESTIONS = [
    "凡纳滨对虾养殖水质的酸碱度要求是什么？",
    "中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？",
    "DB36 和 DB46 两个标准对养殖水体溶解氧的最低要求是否一致？",
]


def stream(question: str, mode: str) -> dict:
    payload = json.dumps({"question": question, "retrieval_mode": mode}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/chat/stream",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    event = None
    answer: list[str] = []
    sources: list[dict] = []
    out: dict = {"mode": mode, "sources": []}
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode().rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
                continue
            if not line.startswith("data: "):
                continue
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if event == "status":
                out["sufficient"] = data.get("sufficient")
                out["gate"] = (data.get("gate") or {}).get("reason")
            elif event == "sources":
                sources = data.get("sources") or []
            elif event == "token":
                answer.append(data.get("text") or data.get("token") or "")
            elif event == "done":
                out["total_ms"] = (data.get("timings") or {}).get("total_ms")
                break
    if not out.get("total_ms"):
        out["total_ms"] = (time.perf_counter() - started) * 1000
    out["answer"] = "".join(answer)
    out["sources"] = [
        {
            "n": s.get("index"),
            "title": (s.get("title") or "")[:26],
            "page": s.get("page"),
            "chunk": (s.get("chunk_id") or "")[:8],
        }
        for s in sources
    ]
    return out


results = {}
for q in QUESTIONS:
    print(f"\n### {q}")
    for mode in MODES:
        r = stream(q, mode)
        r["question"] = q
        results.setdefault(mode, []).append(r)
        print(
            f"  {mode:<13} total={r['total_ms']/1000:5.2f}s "
            f"sufficient={str(r.get('sufficient')):<5} "
            f"gate={r.get('gate')} sources={len(r['sources'])} "
            f"answer={r['answer'][:60]!r}"
        )
        time.sleep(0.5)

print("\n\n## latency (s)")
for mode in MODES:
    vals = [r["total_ms"] / 1000 for r in results[mode]]
    print(
        f"  {mode:<13} mean={statistics.mean(vals):5.2f} "
        f"median={statistics.median(vals):5.2f} min={min(vals):5.2f} max={max(vals):5.2f}"
    )

print("\n## top-5 source overlap vs hybrid_rerank (identical chunk ids)")
for i, q in enumerate(QUESTIONS):
    ref = {s["chunk"] for s in results["hybrid_rerank"][i]["sources"]}
    print(f"  Q{i+1}: {q[:28]}")
    for mode in MODES:
        cur = {s["chunk"] for s in results[mode][i]["sources"]}
        jac = len(ref & cur) / len(ref | cur) if ref | cur else 0
        print(f"    {mode:<13} overlap={jac:4.2f}  ({len(ref & cur)}/{len(ref | cur)})")

print("\n## rerank position of the winning source")
for i, q in enumerate(QUESTIONS):
    print(f"  Q{i+1}:")
    for mode in MODES:
        names = [f"{s['chunk']}@{s['page']}" for s in results[mode][i]["sources"]]
        print(f"    {mode:<13} {' > '.join(names)}")

json.dump(results, open("/tmp/mode-compare.json", "w"), ensure_ascii=False, indent=2)
