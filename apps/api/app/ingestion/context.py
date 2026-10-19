"""Build retrieval-only context for a chunk.

The original chunk text remains the citation source.  Context is metadata
(title / heading path / species) prepended only for indexing, so a chunk such
as "出现上述情况时，应增加监测频率" remains retrievable without rewriting the
evidence that will be shown to the user.
"""

from __future__ import annotations

from app.species import normalize_species_list


def build_context_text(
    *,
    title: str,
    heading_path: list[str] | None,
    species: list[str] | None,
    content: str,
    block_type: str | None = None,
) -> str:
    parts = [f"文档：{title}"]
    if heading_path:
        parts.append("章节：" + " / ".join(str(item) for item in heading_path if item))
    parts.append("适用品种：" + "、".join(normalize_species_list(species)))
    if block_type == "table":
        parts.append("内容类型：表格（保留表头与单位）")
    elif block_type:
        parts.append(f"内容类型：{block_type}")
    return "\n".join(parts) + "\n原文：\n" + content
