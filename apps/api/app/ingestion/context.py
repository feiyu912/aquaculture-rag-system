"""Build retrieval-only context for a chunk.

The original chunk text remains the citation source.  Context is metadata
(title / heading path / species) prepended only for indexing, so a chunk such
as "出现上述情况时，应增加监测频率" remains retrievable without rewriting the
evidence that will be shown to the user.
"""

from __future__ import annotations

import re

from app.species import normalize_species_list

# A PDF block such as "100 mg/L 的漂白粉..." can be misclassified as a heading
# by the generic numbering rule.  These guards are intentionally conservative:
# a real section title is short and does not look like a sentence/quantity.
BODY_SENTENCE_RE = re.compile(r"[。！？；]")
QUANTITY_HEADING_RE = re.compile(r"^\d+(?:\.\d+)?\s*(?:mg|g|kg|ml|l|℃|%|‰)", re.IGNORECASE)


def sanitize_heading_path(heading_path: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    for item in heading_path or []:
        text = str(item).strip()
        if not text:
            continue
        if len(text) > 48 or BODY_SENTENCE_RE.search(text) or QUANTITY_HEADING_RE.match(text):
            continue
        cleaned.append(text)
    return cleaned


def build_context_text(
    *,
    title: str,
    heading_path: list[str] | None,
    species: list[str] | None,
    content: str,
    block_type: str | None = None,
) -> str:
    parts = [f"文档：{title}"]
    cleaned_headings = sanitize_heading_path(heading_path)
    if cleaned_headings:
        parts.append("章节：" + " / ".join(cleaned_headings))
    parts.append("适用品种：" + "、".join(normalize_species_list(species)))
    if block_type == "table":
        parts.append("内容类型：表格（保留表头与单位）")
    elif block_type:
        parts.append(f"内容类型：{block_type}")
    return "\n".join(parts) + "\n原文：\n" + content
