"""Controlled vocabulary for document authority.

The thesis requirement is explicit: a formal standard, a draft for comment, a
technical guidance article and a historical regulation must never be mixed.
A free-text ``document_status`` column cannot guarantee that, so the value is
normalised here and stored in ``kb_documents.authority_level``.

Ordering is significant: it is used to rank evidence and to decide whether a
claim about "current" rules may be answered.
"""

from __future__ import annotations

# Most authoritative first.  ``rank`` is len(levels) - index, so a higher rank
# means a stronger source.  Do not reorder casually: experiments report ranks.
AUTHORITY_LEVELS: tuple[str, ...] = (
    "national_standard",  # 国家标准 GB / GB-T
    "industry_standard",  # 行业标准 SC-T / NY-T
    "local_standard",  # 地方标准 DB**
    "international",  # FAO / WOAH 等国际资料
    "standard_draft",  # 征求意见稿 / 报批稿：不得当作现行依据
    "official_technical",  # 部委/推广站技术指导、明白纸、测报
    "local_guidance",  # 地方农业农村部门建议、技术文章
    "peer_reviewed",  # 期刊论文
    "historical",  # 已被替代或明确过时的规范
    "synthetic",  # 合成演示资料，仅开发用
    "unknown",
)

_RANK = {level: len(AUTHORITY_LEVELS) - index for index, level in enumerate(AUTHORITY_LEVELS)}

# Aliases seen in uploads / crawled metadata.  Keys are lower-cased and stripped.
_ALIASES: dict[str, str] = {
    "formal": "local_standard",
    "draft": "standard_draft",
    "standard": "national_standard",
    "national": "national_standard",
    "gb": "national_standard",
    "gbt": "national_standard",
    "industry": "industry_standard",
    "sct": "industry_standard",
    "nyt": "industry_standard",
    "local": "local_standard",
    "db": "local_standard",
    "guidance": "local_guidance",
    "article": "local_guidance",
    "technical": "official_technical",
    "notice": "official_technical",
    "fao": "international",
    "woah": "international",
    "oie": "international",
    "paper": "peer_reviewed",
    "journal": "peer_reviewed",
    "synthetic": "synthetic",
}

# Levels that may never be treated as a currently enforceable rule.
NON_BINDING_LEVELS = frozenset({"standard_draft", "historical", "synthetic", "unknown"})

# A claim about the *current* rule requires one of these.
BINDING_LEVELS = frozenset(
    {"national_standard", "industry_standard", "local_standard", "official_technical"}
)


def normalize_authority(value: str | None) -> str:
    """Map free text to a controlled level. Unknown input is never upgraded."""
    if value is None:
        return "unknown"
    cleaned = value.strip().lower().replace("-", "").replace("_", "")
    if not cleaned:
        return "unknown"
    if cleaned in _ALIASES:
        return _ALIASES[cleaned]
    # Direct level names (with separators removed) also resolve.
    for level in AUTHORITY_LEVELS:
        if cleaned == level.replace("_", ""):
            return level
    return "unknown"


def authority_rank(value: str | None) -> int:
    return _RANK.get(normalize_authority(value), 0)


def is_binding(value: str | None) -> bool:
    return normalize_authority(value) in BINDING_LEVELS


def describe(value: str | None) -> str:
    """Human-readable Chinese label, used by the API and prompt."""
    return {
        "national_standard": "国家标准",
        "industry_standard": "行业标准",
        "local_standard": "地方标准",
        "international": "国际资料",
        "standard_draft": "征求意见稿",
        "official_technical": "官方技术文件",
        "local_guidance": "地方技术指导",
        "peer_reviewed": "同行评议文献",
        "historical": "历史规范",
        "synthetic": "合成演示资料",
        "unknown": "效力未标注",
    }[normalize_authority(value)]