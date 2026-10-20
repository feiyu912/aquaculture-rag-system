"""Validate DeepSeek credentials without ever printing the API key."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.config import settings


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true", help="also make one minimal chat call")
    args = parser.parse_args()

    key = settings.deepseek_api_key.strip()
    if not key:
        print(
            json.dumps(
                {"ok": False, "error": "DEEPSEEK_API_KEY is not configured"},
                ensure_ascii=False,
            )
        )
        return 2
    base = settings.deepseek_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{base}/models", headers=headers)
        print(
            json.dumps(
                {
                    "ok": response.status_code < 400,
                    "status": response.status_code,
                    "model": settings.deepseek_model,
                    "base_url": base,
                },
                ensure_ascii=False,
            )
        )
        if response.status_code >= 400:
            return 1
        if not args.generate:
            return 0
        payload = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": "只回答一个词。"},
                {"role": "user", "content": "回复：连通"},
            ],
            "temperature": 0,
            "max_tokens": 512,
            "stream": False,
        }
        chat = await client.post(f"{base}/chat/completions", headers=headers, json=payload)
        body = (
            chat.json()
            if chat.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        message = ((body.get("choices") or [{}])[0].get("message") or {}).get("content")
        print(
            json.dumps(
                {
                    "generation_status": chat.status_code,
                    "content": message,
                    "usage": body.get("usage"),
                },
                ensure_ascii=False,
            )
        )
        return 0 if chat.status_code < 400 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
