"""Polite HTTP fetching with provenance capture.

Every fetch records: final URL, HTTP status, content type, byte size, SHA-256
and fetch time.  Those fields become the document version's provenance, so a
later reviewer can prove *what* was retrieved and *when*.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.collection import robots

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; AquacultureRAG/0.1; academic-research; "
    "+https://github.com/; contact via university)"
)
DEFAULT_MIN_INTERVAL_S = 2.0
DEFAULT_MAX_BYTES = 30 * 1024 * 1024

_last_hit: dict[str, float] = {}


class FetchError(RuntimeError):
    pass


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str | None
    body: bytes
    sha256: str
    fetched_at: datetime
    robots: robots.RobotsDecision
    headers: dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.body)

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "content_type": self.content_type,
            "bytes": self.size,
            "sha256": self.sha256,
            "fetched_at": self.fetched_at.isoformat(),
            "robots": self.robots.as_dict(),
        }


async def _throttle(url: str, min_interval: float) -> None:
    host = httpx.URL(url).host or ""
    last = _last_hit.get(host)
    if last is not None:
        wait = min_interval - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
    _last_hit[host] = time.monotonic()


async def fetch(
    url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    min_interval: float = DEFAULT_MIN_INTERVAL_S,
    timeout: float = 40.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    retries: int = 2,
) -> FetchResult:
    decision = await robots.check(url, user_agent=user_agent)
    if not decision.allowed:
        raise FetchError(
            f"robots {decision.policy} for {url}: {decision.reason}"
        )

    await _throttle(url, min_interval)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=15.0),
                follow_redirects=True,
                headers={"User-Agent": user_agent, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            ) as client:
                response = await client.get(url)
            if response.status_code >= 500 and attempt < retries:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code} for {url}")
            body = response.content
            if len(body) > max_bytes:
                raise FetchError(f"response exceeds {max_bytes} bytes: {url}")
            return FetchResult(
                url=url,
                final_url=str(response.url),
                status=response.status_code,
                content_type=response.headers.get("content-type"),
                body=body,
                sha256=hashlib.sha256(body).hexdigest(),
                fetched_at=datetime.now(UTC),
                robots=decision,
                headers={
                    key: response.headers[key]
                    for key in ("last-modified", "etag", "content-length")
                    if key in response.headers
                },
            )
        except (httpx.HTTPError, FetchError) as exc:
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            raise
    raise FetchError(str(last_error))


def reset_throttle() -> None:
    _last_hit.clear()