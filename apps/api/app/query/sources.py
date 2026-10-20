"""Explicit source anchors extracted from the question.

A comparison question may name the standards it compares, e.g.
``DB36 和 DB46 两个标准对养殖水体溶解氧的最低要求是否一致？``.  Retrieving one
global ranked list lets the more verbose document crowd the other cited source
out of the evidence window.  These helpers are deliberately deterministic and
explainable:

* :func:`extract_source_anchors` only recognises standard codes that literally
  occur in the question; it never guesses a source;
* :func:`matches_title` resolves an anchor against the document title, not
  against gold chunks;
* :func:`facet_terms` / :func:`facet_covered` restrict an anchor's candidates
  to passages that mention the asked water parameter.  This is an evidence
  *requirement*, not a lowered sufficiency threshold.

An anchor that matches no active document produces no evidence slot; the trace
records why instead of fabricating coverage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.query.ir import QueryIR

# Standard-code prefixes used by Chinese fishery standards.  ``T`` (推荐性) is
# optional and may appear before or after the number (``DB36/T``, ``GB/T 11607``).
STANDARD_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<prefix>DB|GB|NY|SC|SN|HJ|SL|QB)"
    r"\s*/?\s*T?\s*"
    r"(?P<number>\d{2,5})"
    r"(?![0-9])",
    re.IGNORECASE,
)

# Document-side wording that denotes the same facet as the query term.
FACET_ALIASES: dict[str, tuple[str, ...]] = {
    "溶解氧": ("溶解氧", "溶氧量", "溶氧"),
    "酸碱度": ("酸碱度", "ph值", "ph"),
    "氨氮": ("氨氮", "总氨氮", "非离子氨"),
    "亚硝酸盐": ("亚硝酸盐", "亚硝氮"),
    "盐度": ("盐度",),
    "水温": ("水温", "温度"),
    "透明度": ("透明度",),
    "总碱度": ("总碱度", "碱度"),
    "硬度": ("硬度",),
    "硫化氢": ("硫化氢",),
}


@dataclass(frozen=True, slots=True)
class SourceAnchor:
    """A standard code literally cited by the user."""

    code: str  # normalised display key, e.g. "DB36"
    raw: str  # exact substring from the question
    position: int  # character offset, keeps question order

    def title_keys(self) -> tuple[str, ...]:
        """Keys matched against an alphanumeric-only document title."""
        alnum = _alnum(self.raw)
        keys = [alnum]
        # "DB36/T" and "DB36" must both match a title written either way.
        without_t = alnum.replace("t", "")
        if without_t and without_t not in keys:
            keys.append(without_t)
        return tuple(key for key in keys if key)

    def as_dict(self) -> dict:
        return {"code": self.code, "raw": self.raw, "position": self.position}


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", text.lower())


def extract_source_anchors(question: str, limit: int = 3) -> list[SourceAnchor]:
    """Return unique standard codes in first-mention order."""
    anchors: list[SourceAnchor] = []
    seen: set[str] = set()
    for match in STANDARD_CODE_RE.finditer(question or ""):
        prefix = match.group("prefix").upper()
        number = match.group("number")
        code = f"{prefix}{number}"
        if code in seen:
            continue
        seen.add(code)
        anchors.append(SourceAnchor(code=code, raw=match.group(0).strip(), position=match.start()))
        if len(anchors) >= limit:
            break
    return anchors


def matches_title(title: str, anchor: SourceAnchor) -> bool:
    """Resolve an anchor against a document title (not against chunk text)."""
    normalized = _alnum(title or "")
    if not normalized:
        return False
    for key in anchor.title_keys():
        start = normalized.find(key)
        while start != -1:
            end = start + len(key)
            # "db36" must not match "db360"; a following letter (db36t) is fine.
            if end >= len(normalized) or not normalized[end].isdigit():
                return True
            start = normalized.find(key, start + 1)
    return False


def facet_terms(ir: QueryIR | None) -> list[str]:
    """Facets whose presence makes a passage an answer candidate."""
    if ir is None:
        return []
    return list(dict.fromkeys([*ir.water_parameters, *ir.diseases]))


def aliases_for(term: str) -> tuple[str, ...]:
    return FACET_ALIASES.get(term, (term,))


def facet_covered(text: str, facets: list[str]) -> bool:
    if not facets:
        return True
    lowered = (text or "").lower()
    return any(alias in lowered for facet in facets for alias in aliases_for(facet))


# Numeric/tolerance cues that mark a passage as stating a *requirement* rather
# than merely mentioning the facet ("确保有足够的溶氧" is not a limit).
THRESHOLD_CUES = (
    "以上",
    "以下",
    "不低于",
    "不高于",
    "不超过",
    "大于",
    "小于",
    "≥",
    "≤",
    "mg/l",
    "ppm",
    "℃",
    "‰",
)


def has_threshold_cue(text: str) -> bool:
    lowered = (text or "").lower()
    return any(cue in lowered for cue in THRESHOLD_CUES)


def order_round_robin(groups: list[list[str]], slots: int) -> list[str]:
    """Interleave per-source results so every cited source appears early.

    ``[[a1, a2], [b1]]`` with ``slots=2`` yields ``[a1, b1, a2]``.  This keeps
    the first evidence slots balanced across the sources the user named, rather
    than letting the single best-ranked document take all of them.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for rank in range(max(0, slots)):
        for group in groups:
            if rank >= len(group):
                continue
            item = group[rank]
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
    return ordered