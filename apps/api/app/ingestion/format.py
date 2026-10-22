"""Content-type detection for the ingestion pipeline.

The upload API used to reject anything that was not a PDF by extension and
magic bytes.  Web sources arrive as saved HTML, so the decision moves here and
is based on the bytes, never on the file name alone (a ``.pdf`` download that
returns an HTML error page must not be parsed as a PDF).
"""

from __future__ import annotations

from pathlib import Path

PDF_MAGIC = b"%PDF"
HTML_SNIFF_BYTES = 4096
HTML_HINTS = (b"<!doctype html", b"<html", b"<head", b"<body", b"<meta")


def detect_format(head: bytes, *, content_type: str | None = None) -> str | None:
    """Return ``"pdf"``, ``"html"`` or ``None`` when the content is unusable."""
    prefix = head[:HTML_SNIFF_BYTES]
    if prefix.startswith(PDF_MAGIC):
        return "pdf"
    lowered = prefix.lstrip().lower()
    if any(hint in lowered for hint in HTML_HINTS):
        return "html"
    if content_type:
        value = content_type.split(";")[0].strip().lower()
        if value == "application/pdf":
            return "pdf"
        if value in {"text/html", "application/xhtml+xml"}:
            return "html"
    return None


def detect_path_format(path: Path, *, content_type: str | None = None) -> str | None:
    try:
        with path.open("rb") as handle:
            head = handle.read(HTML_SNIFF_BYTES)
    except OSError:
        return None
    return detect_format(head, content_type=content_type)


def extension_for(fmt: str) -> str:
    return {"pdf": ".pdf", "html": ".html"}[fmt]