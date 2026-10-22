"""Resolve a repository landing page to an actual downloadable file.

Only DSpace-based repositories need this step.  The resolver reads the item's
ORIGINAL bundle and returns the first PDF bitstream, together with the licence
and issue date declared on the item — those are the fields that decide whether
the material may be stored at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.collection.fetch import DEFAULT_USER_AGENT


class ResolveError(RuntimeError):
    pass


@dataclass(slots=True)
class ResolvedDocument:
    url: str
    title: str | None
    issued: str | None
    license: str | None
    item_uuid: str


def _meta(item: dict, key: str) -> str | None:
    values = (item.get("metadata") or {}).get(key) or []
    if not values:
        return None
    return values[0].get("value")


async def resolve_worldfish(item_page: str, *, timeout: float = 40.0) -> ResolvedDocument:
    uuid = item_page.rstrip("/").rsplit("/", 1)[-1]
    if len(uuid) != 36:
        raise ResolveError(f"not a DSpace item URL: {item_page}")

    base = "https://digitalarchive.worldfishcenter.org/server/api"
    headers = {"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=True
    ) as client:
        item_resp = await client.get(f"{base}/core/items/{uuid}", headers=headers)
        item_resp.raise_for_status()
        item = item_resp.json()

        bundles_resp = await client.get(f"{base}/core/items/{uuid}/bundles", headers=headers)
        bundles_resp.raise_for_status()
        bundles = (bundles_resp.json().get("_embedded") or {}).get("bundles") or []
        original = next((b for b in bundles if b.get("name") == "ORIGINAL"), None)
        if original is None:
            raise ResolveError(f"no ORIGINAL bundle for {uuid}")

        bits_resp = await client.get(
            f"{base}/core/bundles/{original['uuid']}/bitstreams", headers=headers
        )
        bits_resp.raise_for_status()
        bitstreams = (bits_resp.json().get("_embedded") or {}).get("bitstreams") or []
        for bitstream in bitstreams:
            name = (bitstream.get("name") or "").lower()
            if name.endswith(".pdf"):
                return ResolvedDocument(
                    url=bitstream["_links"]["content"]["href"],
                    title=_meta(item, "dc.title"),
                    issued=_meta(item, "dc.date.issued"),
                    license=_meta(item, "dc.rights") or _meta(item, "dc.rights.uri"),
                    item_uuid=uuid,
                )
    raise ResolveError(f"no PDF bitstream for {uuid}")


async def resolve(spec) -> ResolvedDocument:
    if spec.resolver == "worldfish":
        return await resolve_worldfish(spec.url)
    return ResolvedDocument(
        url=spec.url, title=spec.title, issued=spec.publish_date, license=spec.license,
        item_uuid="",
    )