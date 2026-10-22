"""Curated source registry.

The registry is the human-reviewed list of what we are allowed to fetch and how
each item should be classified.  It is deliberately a file (not a crawler
frontier): the thesis must be able to state exactly which URLs were selected,
why, and under which authority level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.authority import normalize_authority
from app.ingestion.format import detect_format

POLICIES = {"auto", "manual"}
DOC_TYPES = {
    "standard",
    "technical_guidance",
    "research",
    "general",
    "qa",
    "terminology",
    "statistics",
}


@dataclass(slots=True)
class SourceSpec:
    id: str
    url: str
    title: str
    publisher: str
    authority: str
    doc_type: str = "technical_guidance"
    language: str = "zh"
    publish_date: str | None = None
    effective_date: str | None = None
    species: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    growth_stages: list[str] = field(default_factory=list)
    region: str | None = None
    policy: str = "auto"
    license: str | None = None
    # ``direct`` fetches the URL as-is.  ``worldfish`` treats the URL as a
    # DSpace item page and resolves the ORIGINAL bundle's PDF bitstream.
    resolver: str = "direct"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.policy not in POLICIES:
            raise ValueError(f"{self.id}: unknown policy {self.policy!r}")
        if self.doc_type not in DOC_TYPES:
            raise ValueError(f"{self.id}: unknown doc_type {self.doc_type!r}")
        if self.resolver not in {"direct", "worldfish"}:
            raise ValueError(f"{self.id}: unknown resolver {self.resolver!r}")
        self.authority = normalize_authority(self.authority)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "publisher": self.publisher,
            "authority": self.authority,
            "doc_type": self.doc_type,
            "language": self.language,
            "publish_date": self.publish_date,
            "effective_date": self.effective_date,
            "species": self.species,
            "topics": self.topics,
            "growth_stages": self.growth_stages,
            "region": self.region,
            "policy": self.policy,
            "license": self.license,
            "resolver": self.resolver,
            "notes": self.notes,
        }

    def format_hint(self) -> str | None:
        suffix = Path(self.url.split("?")[0]).suffix.lower()
        if suffix == ".pdf":
            return "pdf"
        if suffix in {".htm", ".html", ".shtml"}:
            return "html"
        return None


def load_registry(path: Path | str) -> list[SourceSpec]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entries = raw.get("sources") or []
    specs: list[SourceSpec] = []
    seen: set[str] = set()
    for entry in entries:
        spec = SourceSpec(**entry)
        if spec.id in seen:
            raise ValueError(f"duplicate source id: {spec.id}")
        seen.add(spec.id)
        specs.append(spec)
    return specs


def detect_fetched_format(body: bytes, content_type: str | None, spec: SourceSpec) -> str:
    fmt = detect_format(body, content_type=content_type)
    if fmt is None:
        fmt = spec.format_hint() or "html"
    return fmt