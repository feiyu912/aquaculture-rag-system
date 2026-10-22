"""Physical source format helpers.

``source_type`` is stored as ``pdf`` or ``html``.  Some early collectors wrote
``web`` for an HTML page; treat it as the same physical format everywhere so a
legacy row is not sent to the PDF reader or shown as a fake PDF page.
"""

from __future__ import annotations


def normalize_media_type(value: str | None) -> str:
    media = (value or "pdf").strip().lower()
    if media in {"html", "web"}:
        return "html"
    if media == "pdf":
        return "pdf"
    return media or "pdf"


def is_pdf_media_type(value: str | None) -> bool:
    return normalize_media_type(value) == "pdf"


def public_location(value: object, media_type: str | None) -> dict | None:
    """Return one location safe for the client's physical format.

    PDF locations keep page/bbox.  HTML locations keep their paragraph/block
    anchor but never expose PDF page/bbox keys; FAQ rows have no location.
    """
    if not isinstance(value, dict) or not value:
        return None
    media = normalize_media_type(media_type)
    if media == "pdf":
        return dict(value)
    if media == "html":
        cleaned = {
            key: item
            for key, item in value.items()
            if key
            not in {
                "page",
                "bbox",
                "page_width",
                "page_height",
                "origin",
                "rotation",
            }
        }
        if cleaned.get("coordinate_system") != "html":
            cleaned.pop("coordinate_system", None)
        return cleaned
    return None


def public_locations(values: object, media_type: str | None) -> list[dict]:
    if not isinstance(values, list):
        return []
    locations = [public_location(value, media_type) for value in values]
    return [location for location in locations if location]


def citation_locations(value: object, media_type: str | None) -> list[dict]:
    """Extract all locations from the legacy ``bbox`` blob.

    New rows store ``{"bbox": ..., "locations": [...]}``.  Old rows store a
    single location object, or (for a very old row) a bare bbox list.
    """
    raw: list[object] = []
    if isinstance(value, dict):
        nested = value.get("locations")
        if isinstance(nested, list):
            raw = nested
        else:
            raw = [value]
    elif isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            raw = value
        elif len(value) == 4:
            raw = [{"bbox": value}]
    return public_locations(raw, media_type)


def max_location_page(locations: list[dict]) -> int | None:
    pages = [
        location.get("page")
        for location in locations
        if isinstance(location.get("page"), int)
    ]
    return max(pages) if pages else None
