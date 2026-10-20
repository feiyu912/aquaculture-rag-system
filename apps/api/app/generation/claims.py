"""Claim-level citation checks (v0).

This is deliberately deterministic and lexical.  It answers "does the cited
quote share enough terms with this claim?"; it does not prove entailment.  Keep
``method`` in every result so a thesis can report the limitation honestly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.generation.support import verify_support

CITATION_RE = re.compile(r"\[(?:S)?(\d+)\]")
SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])")
SKIP_PREFIXES = ("以上内容", "根据知识库中的资料", "具体养殖决策", "注意：", "注：")
HEADING_RE = re.compile(r"^\s*[一二三四五六七八九十]+[、.．]\s*")


@dataclass(slots=True)
class ClaimCheck:
    claim: str
    cited_indices: list[int] = field(default_factory=list)
    status: str = "uncited"
    score: float = 0.0
    method: str = "lexical_overlap_v0"
    matched_terms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "claim": self.claim,
            "cited_indices": self.cited_indices,
            "status": self.status,
            "score": self.score,
            "method": self.method,
            "matched_terms": self.matched_terms,
        }


def _strip_markup(text: str) -> str:
    text = re.sub(r"^\s*(?:[-*]|\d+[.、)])\s*", "", text)
    text = HEADING_RE.sub("", text)
    return text.strip()


def _table_claim(line: str) -> str | None:
    """Turn a cited markdown table data row into a checkable claim.

    Tables are a common answer shape for numeric limits.  Header/separator
    rows have no citation and are ignored; a data row is only kept when it
    carries at least one ``[S1]`` marker.  This is still a lexical check, not
    table-cell entailment.
    """
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    cells = [cell for cell in cells if cell]
    if not cells:
        return None
    if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
        return None
    if not any(CITATION_RE.search(cell) for cell in cells):
        return None
    claim = " ".join(cells)
    # Table cells can be numeric-only (e.g. "pH | 6.5~8.5"), so unlike prose
    # claims we do not require a CJK character here.
    return claim if len(claim) >= 8 else None


def split_claims(answer: str) -> list[str]:
    claims: list[str] = []
    seen: set[str] = set()
    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(SKIP_PREFIXES):
            continue
        if line.startswith("|"):
            table_claim = _table_claim(line)
            if table_claim is None:
                continue
            if table_claim not in seen:
                seen.add(table_claim)
                claims.append(table_claim)
            continue
        line = _strip_markup(line)
        line_indices = CITATION_RE.findall(line)
        for sentence in SENTENCE_RE.split(line):
            claim = sentence.strip()
            if len(claim) < 8:
                continue
            if not re.search(r"[\u4e00-\u9fff]", claim):
                continue
            # A bullet often puts its source marker at the end while the
            # preceding sentences belong to the same cited claim. Propagate
            # only within that bullet, never across bullets.
            if line_indices and not CITATION_RE.search(claim):
                marker = "".join(f"[S{index}]" for index in line_indices)
                claim = claim.rstrip("。；;") + f"{marker}。"
            if claim not in seen:
                seen.add(claim)
                claims.append(claim)
    return claims


def _evidence_map(evidence: list[dict]) -> dict[int, str]:
    mapped: dict[int, str] = {}
    for item in evidence:
        index = item.get("index", item.get("source_index"))
        quote = item.get("quote") or item.get("content") or ""
        if index is not None:
            mapped[int(index)] = quote
    return mapped


def verify_claims(answer: str, evidence: list[dict]) -> list[dict]:
    quotes = _evidence_map(evidence)
    results: list[ClaimCheck] = []
    for claim in split_claims(answer):
        indices = sorted({int(match) for match in CITATION_RE.findall(claim)})
        if not indices:
            results.append(ClaimCheck(claim=claim, status="uncited"))
            continue
        checks = [verify_support(claim, quotes.get(index, "")) for index in indices]
        supported = [check for check in checks if check.status == "supported"]
        weak = [check for check in checks if check.status == "weak"]
        if supported:
            best = supported[0]
            status = "supported"
        elif weak:
            best = weak[0]
            status = "weak"
        else:
            best = checks[0]
            status = "unverified"
        results.append(
            ClaimCheck(
                claim=claim,
                cited_indices=indices,
                status=status,
                score=best.score,
                method=best.method,
                matched_terms=best.matched_terms,
            )
        )
    return [result.as_dict() for result in results]


def summarize_claims(claims: list[dict]) -> dict:
    total = len(claims)
    supported = sum(1 for claim in claims if claim.get("status") == "supported")
    weak = sum(1 for claim in claims if claim.get("status") == "weak")
    uncited = sum(1 for claim in claims if claim.get("status") == "uncited")
    unverified = sum(1 for claim in claims if claim.get("status") == "unverified")
    return {
        "total": total,
        "supported": supported,
        "weak": weak,
        "unverified": unverified,
        "uncited": uncited,
        "support_rate": round(supported / total, 3) if total else 0.0,
        "method": "lexical_overlap_v0",
    }
