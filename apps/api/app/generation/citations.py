from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION_RE = re.compile(r"[\[【]([^\]】]{1,80})[\]】]")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")
FACTUAL_HINTS = (
    "是",
    "为",
    "应",
    "可",
    "需",
    "要",
    "适合",
    "不宜",
    "保持",
    "控制",
    "投喂",
    "浓度",
    "温度",
    "盐度",
    "溶解氧",
    "氨氮",
    "亚硝酸盐",
    "ph",
    "mg",
    "克",
    "天",
    "%",
)


@dataclass(slots=True)
class CitationReport:
    cited_indices: list[int] = field(default_factory=list)
    invalid_indices: list[int] = field(default_factory=list)
    cited_factual: int = 0
    factual_sentences: int = 0
    coverage: float = 1.0

    @property
    def valid(self) -> bool:
        return not self.invalid_indices

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "cited_indices": self.cited_indices,
            "invalid_indices": self.invalid_indices,
            "cited_factual": self.cited_factual,
            "factual_sentences": self.factual_sentences,
            "coverage": round(self.coverage, 3),
        }


def parse_citations(text: str) -> list[int]:
    indices: list[int] = []
    seen: set[int] = set()
    for match in CITATION_RE.finditer(text):
        body = match.group(1)
        for part in re.split(r"[,，、;；\s]+", body):
            token = part.strip().lstrip("Ss").strip()
            if token.isdigit():
                value = int(token)
                if value not in seen:
                    seen.add(value)
                    indices.append(value)
    return indices


def _is_factual(sentence: str) -> bool:
    stripped = CITATION_RE.sub("", sentence).strip()
    if len(stripped) < 6:
        return False
    if re.search(r"\d", stripped):
        return True
    lowered = stripped.lower()
    return any(hint in lowered for hint in FACTUAL_HINTS)


def validate_answer(text: str, max_index: int) -> CitationReport:
    """Deterministic citation check.

    This checks existence, not whether the source actually supports the claim.
    Support verification is a separate, offline/optional step.
    """
    cited = parse_citations(text)
    invalid = [index for index in cited if index < 1 or index > max_index]

    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    factual = [s for s in sentences if _is_factual(s)]
    cited_factual = 0
    for sentence in factual:
        sentence_indices = parse_citations(sentence)
        if any(1 <= index <= max_index for index in sentence_indices):
            cited_factual += 1

    coverage = (cited_factual / len(factual)) if factual else 1.0
    return CitationReport(
        cited_indices=cited,
        invalid_indices=invalid,
        cited_factual=cited_factual,
        factual_sentences=len(factual),
        coverage=coverage,
    )
