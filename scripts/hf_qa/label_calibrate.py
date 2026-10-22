#!/usr/bin/env python3
"""Stage 2: LLM labelling of the calibration sample.

Labels each sampled QA via the aigateway OpenAI-compatible endpoint
(deepseek-v4.1-flash), concurrency 8, incremental (resumable), with explicit
error accounting — a failed label is never silently dropped.

CN strata answer: is this QA aquaculture?  (aquaculture | other | unsure + domain)
EN quality stratum: does the response concretely answer the question?
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "hf_qa" / "processed"
LABELED = OUT / "labeled_sample.jsonl"

CONCURRENCY = 16
TIMEOUT_S = 90
MAX_RETRY = 3


def load_llm_config() -> dict:
    env = {}
    with open(ROOT / "apps" / "api" / ".env", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return {
        "base_url": env["OPENAI_BASE_URL"],
        "api_key": env["OPENAI_API_KEY"],
        "model": env["OPENAI_MODEL"],
    }


CN_PROMPT = """判断下面这条中文问答是否属于「水产养殖」范畴。

水产养殖定义：对鱼、虾、蟹、贝、藻、鳖、蛙、海参等水生生物的人工养殖活动，涵盖养殖管理、苗种繁育、病害防治、水质调控、饲料投喂、养殖设施、产品流通质检等。
不属于：种植业（粮棉果蔬花卉）、陆生畜禽养殖（猪牛羊鸡鸭鹅等，含水禽）、观赏园艺、食品加工业、餐饮生活常识。

只输出 JSON：{{"label": "aquaculture|other|unsure", "domain": "fish|shrimp|crab|shellfish|algae|turtle_frog|other_aqua|livestock|crop|ornamental|food_processing|other", "reason": "不超过25字"}}

问题：{q}
答案：{a}"""

EN_PROMPT = """Judge whether this English aquaculture Q&A pair is a good, usable QA item.

"good" = the response directly and concretely answers the question with substantive content.
"weak" = response is partially relevant, generic, or padded with filler.
"bad" = response does not answer the question, is contradictory, or is unusable.

Output only JSON: {{"label": "good|weak|bad", "reason": "max 25 words"}}

Question: {q}
Response: {a}"""


import re

BRACE_RE = re.compile(r"\{.*\}", re.DOTALL)
LABEL_RE = re.compile(r'"label"\s*:\s*"(aquaculture|other|unsure|good|weak|bad)"')


def parse_label(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    m = BRACE_RE.search(text)
    if m:
        try:
            data = json.loads(m.group(0))
            if data.get("label"):
                return data
        except json.JSONDecodeError:
            pass
    m = LABEL_RE.search(text)
    if m:
        return {"label": m.group(1), "domain": "", "reason": text[:60]}
    raise ValueError(f"no label in response: {text[:80]!r}")


async def label_one(client: AsyncOpenAI, model: str, row: dict, sem: asyncio.Semaphore, stats: dict) -> dict:
    if row["stratum"] == "en_quality":
        prompt = EN_PROMPT.format(q=row["question"], a=row["answer"])
    else:
        prompt = CN_PROMPT.format(q=row["question"], a=row["answer"])
    async with sem:
        for attempt in range(1, MAX_RETRY + 1):
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=1000,
                    timeout=TIMEOUT_S,
                )
                text = resp.choices[0].message.content or ""
                if not text.strip():
                    # v4.1-flash is a reasoning model: when max_tokens runs out
                    # on reasoning, content is empty — fall back to the
                    # reasoning text, which usually states the label.
                    text = str(getattr(resp.choices[0].message, "reasoning_content", "") or "")
                data = parse_label(text)
                row["llm_label"] = data.get("label", "parse_error")
                row["llm_domain"] = data.get("domain", "")
                row["llm_reason"] = data.get("reason", "")
                stats["ok"] += 1
                return row
            except Exception as exc:  # noqa: BLE001
                if attempt == MAX_RETRY:
                    row["llm_label"] = "error"
                    row["llm_reason"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                    stats["error"] += 1
                    return row
                await asyncio.sleep(2 * attempt)


async def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(OUT / "calibration_sample.jsonl"))
    ap.add_argument("--output", default=str(LABELED))
    args = ap.parse_args()
    in_path, out_path = Path(args.input), Path(args.output)

    cfg = load_llm_config()
    rows = [json.loads(l) for l in open(in_path, encoding="utf-8")]
    done: set[str] = set()
    if out_path.exists():
        for l in open(out_path, encoding="utf-8"):
            r = json.loads(l)
            done.add(f"{r['stratum']}:{r['original_id']}")
    todo = [r for r in rows if f"{r['stratum']}:{r['original_id']}" not in done]
    print(f"total={len(rows)} done={len(done)} todo={len(todo)}")

    client = AsyncOpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
    sem = asyncio.Semaphore(CONCURRENCY)
    stats = {"ok": 0, "error": 0}
    lock = asyncio.Lock()
    with open(out_path, "a", encoding="utf-8") as f:

        async def run_one(row: dict) -> None:
            r = await label_one(client, cfg["model"], row, sem, stats)
            async with lock:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                n = stats["ok"] + stats["error"]
                if n % 100 == 0:
                    print(f"progress {n} (ok={stats['ok']} err={stats['error']})", flush=True)

        await asyncio.gather(*(run_one(r) for r in todo))
    print(f"FINISHED ok={stats['ok']} error={stats['error']}")
    if stats["error"]:
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
