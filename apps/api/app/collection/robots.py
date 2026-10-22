"""robots.txt enforcement for the collector.

Rules follow RFC 9309:

* 2xx  -> parse and obey the rules
* 4xx  -> "unavailable": no restrictions (this is why ``nftec.agri.cn`` returning
          403 for /robots.txt is still allowed)
* 5xx / network failure -> "unreachable": treated as disallowed

There is deliberately **no bypass switch**.  A site that disallows crawling is
recorded as ``disallowed`` and must be sourced manually; the thesis needs a
defensible audit trail, not a maximum document count.
"""

from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

CACHE_TTL_SECONDS = 6 * 60 * 60
_cache: dict[str, tuple[float, "RobotsDecision"]] = {}


@dataclass(frozen=True, slots=True)
class RobotsDecision:
    host: str
    policy: str  # allowed | disallowed | unavailable | unreachable
    status: int | None
    reason: str

    @property
    def allowed(self) -> bool:
        return self.policy in {"allowed", "unavailable"}

    def as_dict(self) -> dict:
        return {
            "host": self.host,
            "policy": self.policy,
            "status": self.status,
            "reason": self.reason,
        }


def _origin(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    root = f"{parsed.scheme}://{parsed.netloc}"
    return host, root


async def check(url: str, *, user_agent: str, timeout: float = 10.0) -> RobotsDecision:
    host, root = _origin(url)
    cached = _cache.get(host)
    now = time.monotonic()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    decision = await _fetch_rules(url, root, user_agent, timeout)
    _cache[host] = (now, decision)
    return decision


async def _fetch_rules(
    url: str, root: str, user_agent: str, timeout: float
) -> RobotsDecision:
    host = urlparse(url).hostname or ""
    robots_url = f"{root}/robots.txt"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=5.0), follow_redirects=True
        ) as client:
            response = await client.get(
                robots_url, headers={"User-Agent": user_agent}
            )
    except httpx.HTTPError as exc:
        # Conservative: a site we cannot reach for robots.txt is not crawled.
        return RobotsDecision(host, "unreachable", None, f"robots fetch failed: {exc}")

    status = response.status_code
    if 200 <= status < 300:
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        allowed = parser.can_fetch(user_agent, url)
        return RobotsDecision(
            host,
            "allowed" if allowed else "disallowed",
            status,
            "robots rules parsed",
        )
    if 400 <= status < 500:
        return RobotsDecision(
            host, "unavailable", status, f"robots.txt returned {status}; RFC 9309: no rules"
        )
    return RobotsDecision(
        host, "unreachable", status, f"robots.txt returned {status}; treated as disallowed"
    )


def reset_cache() -> None:
    """Test helper: drop cached decisions."""
    _cache.clear()