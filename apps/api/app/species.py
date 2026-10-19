from __future__ import annotations

import re

GENERAL_SPECIES = "通用"
MAX_SPECIES = 20
SPECIES_SPLIT_RE = re.compile(r"[,，、;；/|]+")
GENERAL_ALIASES = {"通用", "全部", "不限", "通用知识", "general", "all"}


def _clean(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def parse_species(raw: str | None) -> list[str]:
    """Normalize a free-text species field.

    Empty input means general knowledge. Specific species win over the reserved
    "通用" marker so a document is never both general and species-specific.
    """
    if raw is None or not raw.strip():
        return [GENERAL_SPECIES]

    result: list[str] = []
    seen: set[str] = set()
    for part in SPECIES_SPLIT_RE.split(raw):
        value = _clean(part)
        if not value:
            continue
        if value.lower() in GENERAL_ALIASES:
            value = GENERAL_SPECIES
        if len(value) > 32:
            raise ValueError("品种名称过长")
        if value not in seen:
            seen.add(value)
            result.append(value)

    if not result:
        return [GENERAL_SPECIES]
    specific = [value for value in result if value != GENERAL_SPECIES]
    if specific:
        return specific[:MAX_SPECIES]
    return [GENERAL_SPECIES]


def normalize_species_list(values: list[str] | None) -> list[str]:
    if not values:
        return [GENERAL_SPECIES]
    return parse_species("、".join(str(value) for value in values))


def species_text(values: list[str] | None) -> str:
    return "、".join(normalize_species_list(values))


def detect_species(question: str, options: list[str]) -> str | None:
    """Return a unique species mentioned in the question.

    Ambiguous questions (two or more species) intentionally return None: a hard
    filter would hide evidence instead of letting the answer discuss both.
    """
    text = question.lower()
    hits: list[str] = []
    for option in sorted(
        {item for item in options if item != GENERAL_SPECIES}, key=len, reverse=True
    ):
        if not option:
            continue
        if option.lower() in text:
            hits.append(option)
            continue
        # "对虾" should select "凡纳滨对虾" when that is the only known species.
        # If several species share the suffix, leave the query unfiltered.
        if any(option.lower()[start:] in text for start in range(1, len(option) - 1)):
            hits.append(option)
    if len(hits) != 1:
        return None
    return hits[0]
