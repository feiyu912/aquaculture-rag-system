#!/usr/bin/env python3
"""Rewrite EN eval reference answers in English, using only their gold evidence.

The build prompt asked for Chinese references, which is wrong for English
questions. This pass keeps questions and gold evidence untouched and only
regenerates the reference answer in the question's language.

Usage: uv run python fix_en_references.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "data" / "hf_qa" / "eval" / "eval_set_v1.jsonl"
BACKUP = ROOT / "data" / "hf_qa" / "eval" / "eval_set_v1.pre_enfix.jsonl"
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_eval_set import load_llm  # noqa: E402

PROMPT = """You are a strict reviewer for aquaculture question answering. Below is an English question and the document evidence that supports it (evidence may be in Chinese). Write the reference answer in ENGLISH, using only facts stated in the evidence.

Output only JSON: {{"reference_answer": "1-3 sentences in English", "reason": "max 20 words"}}

Question: {q}

Evidence:
{evidence}"""


async def main() -> None:
    rows = [json.loads(l) for l in open(EVAL, encoding="utf-8")]
    if not BACKUP.exists():
        BACKUP.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    client, model = load_llm()
    sem = asyncio.Semaphore(4)
    fixed = 0

    async def fix(row: dict) -> None:
        nonlocal fixed
        evidence = "\n".join(
            f"[{i}] {g.get('content_head') or g.get('quote', '')}"
            for i, g in enumerate(row["gold_evidence"], start=1)
        )
        prompt = PROMPT.format(q=row["question"], evidence=evidence)
        async with sem:
            for _ in range(2):
                try:
                    resp = await client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": prompt}],
                        temperature=0.0, max_tokens=800, timeout=90,
                    )
                    text = resp.choices[0].message.content or ""
                    if not text.strip():
                        text = str(getattr(resp.choices[0].message, "reasoning_content", "") or "")
                    s, e = text.find("{"), text.rfind("}")
                    if s >= 0 and e > s:
                        data = json.loads(text[s : e + 1])
                        if data.get("reference_answer"):
                            row["reference_answer"] = data["reference_answer"].strip()
                            row["reference_language"] = "en"
                            fixed += 1
                            return
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(2)

    await asyncio.gather(*(fix(r) for r in rows if r["language"] == "en"))
    with open(EVAL, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"EN references rewritten: {fixed}/{sum(1 for r in rows if r['language']=='en')}")


if __name__ == "__main__":
    asyncio.run(main())