"""Validate the configured chat-completions provider without printing its key.

Supports LLM_PROVIDER=deepseek and LLM_PROVIDER=openai_compatible.
"""

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


def endpoint() -> tuple[str, str, str]:
    if settings.llm_provider == "deepseek":
        return (
            settings.deepseek_base_url.rstrip("/"),
            settings.deepseek_api_key.strip(),
            settings.deepseek_model,
        )
    if settings.llm_provider in {"openai_compatible", "openai"}:
        return (
            settings.openai_base_url.rstrip("/"),
            settings.openai_api_key.strip(),
            settings.openai_model,
        )
    raise SystemExit(f"LLM_PROVIDER={settings.llm_provider!r} does not call an external API")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true", help="also make one minimal chat call")
    args = parser.parse_args()

    base, key, model = endpoint()
    missing = [
        name
        for name, value in (("base_url", base), ("api_key", key), ("model", model))
        if not value
    ]
    if missing:
        print(
            json.dumps(
                {"ok": False, "provider": settings.llm_provider, "missing": missing},
                ensure_ascii=False,
            )
        )
        return 2

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{base}/models", headers=headers)
        models_ok = response.status_code < 400
        print(
            json.dumps(
                {
                    "ok": models_ok if not args.generate else None,
                    "provider": settings.llm_provider,
                    "models_status": response.status_code,
                    "model": model,
                    "base_url": base,
                    "note": "gateway may not implement /models; --generate checks chat directly"
                    if not models_ok
                    else None,
                },
                ensure_ascii=False,
            )
        )
        if not args.generate:
            return 0 if models_ok else 1
        payload = {
            "model": model,
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
                    "ok": chat.status_code < 400 and bool(message),
                    "generation_status": chat.status_code,
                    "finish_reason": ((body.get("choices") or [{}])[0]).get("finish_reason"),
                    "content": message,
                    "usage": body.get("usage"),
                },
                ensure_ascii=False,
            )
        )
        return 0 if chat.status_code < 400 and bool(message) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
