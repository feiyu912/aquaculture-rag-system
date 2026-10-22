from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass

from app.ingestion.context import sanitize_heading_path
from app.ingestion.parser import CJK_RE, ParsedBlock, ParsedDocument

CHUNK_NAMESPACE = uuid.UUID("6f1f5d8e-3f6a-4c2b-9d7e-2a1b3c4d5e6f")
# Chinese sentences end with a full-width mark; Latin sentences end with a dot
# followed by whitespace and a capital/quote.  Decimal points ("1.5") and
# abbreviations followed by a lower-case word ("e.g. it") are left intact.
SENTENCE_RE = re.compile(r"(?<=[。！？；;])|(?<=[.!?])(?=\s+[\"'(A-Z0-9])")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _token_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", text))


@dataclass(slots=True)
class ChunkDraft:
    id: uuid.UUID
    parent_id: uuid.UUID | None
    role: str
    ordinal: int
    content: str
    heading_path: list[str]
    block_type: str
    page_from: int
    page_to: int
    token_count: int
    locations: list[dict]


def _merge_locations(blocks: list[ParsedBlock]) -> list[dict]:
    by_page: dict[int, dict] = {}
    for block in blocks:
        loc = block.location()
        current = by_page.get(block.page)
        if current is None:
            by_page[block.page] = loc
            continue
        # Web locations have no geometry to merge; the first block's anchor is
        # the stable jump target for the whole group.
        if "bbox" not in loc or "bbox" not in current:
            continue
        x0 = min(current["bbox"][0], loc["bbox"][0])
        y0 = min(current["bbox"][1], loc["bbox"][1])
        x1 = max(current["bbox"][2], loc["bbox"][2])
        y1 = max(current["bbox"][3], loc["bbox"][3])
        current["bbox"] = [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]
    return [by_page[p] for p in sorted(by_page)]


def _join_blocks(blocks: list[ParsedBlock]) -> str:
    """Join line-level PDF blocks into readable paragraph text."""
    out = ""
    prev_block: ParsedBlock | None = None
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if not out:
            out = text
            prev_block = block
            continue
        prev = out[-1]
        size_jump = (
            prev_block is not None
            and prev_block.font_size is not None
            and block.font_size is not None
            and abs(prev_block.font_size - block.font_size) > 1.5
        )
        if (
            block.heading_level > 0
            or block.block_type == "table"
            or prev in "。！？；："
            or text[0] in "•-—"
            or size_jump
        ):
            out += "\n" + text
        elif CJK_RE.match(prev) or CJK_RE.match(text[0]):
            out += text
        else:
            out += " " + text
        prev_block = block
    return out


def _hard_split(text: str, target: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target)
        if end < len(text):
            # Prefer a punctuation boundary in the last 20% of the window.
            window_start = max(start + int(target * 0.8), start + 1)
            for pos in range(end, window_start, -1):
                if text[pos - 1] in "。！？!?；;，,\n":
                    end = pos
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _overlap_tail(text: str, overlap: int) -> str:
    """Trailing context for the next chunk, without cutting a Latin word."""
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    if any("\u4e00" <= ch <= "\u9fff" for ch in tail):
        return tail  # CJK has no word delimiter; characters are safe to cut
    space = tail.find(" ")
    if space > 0:
        return tail[space + 1 :]
    return ""


def _split_text(text: str, target: int, overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= target:
        return [text] if text else []

    sentences = [s for s in SENTENCE_RE.split(text) if s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > target * 1.5:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(sentence, target, overlap))
            continue
        if not current:
            current = sentence
        elif len(current) + len(sentence) <= target:
            current += sentence
        else:
            chunks.append(current)
            tail = _overlap_tail(current, overlap)
            joiner = " " if tail and not tail.endswith(" ") and not sentence[:1].isspace() else ""
            current = (tail + joiner + sentence).strip()
    if current.strip():
        chunks.append(current)

    # Remove trailing duplicates produced by overlap on very short parents.
    deduped: list[str] = []
    for chunk in chunks:
        if not deduped or chunk.strip() != deduped[-1].strip():
            deduped.append(chunk.strip())
    return deduped


def _split_table(text: str, target: int, overlap: int) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(text) <= target * 1.5 or len(lines) <= 3:
        return [text]
    header, body = lines[:2], lines[2:]
    chunks: list[str] = []
    current = header[:]
    for row in body:
        current.append(row)
        if sum(len(line) + 1 for line in current) >= target:
            chunks.append("\n".join(current))
            current = header[:]
    if len(current) > len(header):
        chunks.append("\n".join(current))
    return chunks or [text]


def build_chunks(
    parsed: ParsedDocument,
    version_id: uuid.UUID,
    parent_target: int = 900,
    child_target: int = 350,
    overlap: int = 60,
) -> list[ChunkDraft]:
    """Structure-aware parent-child chunking.

    Heading blocks start new parents; tables stay together as a table parent.
    Parent content is used for generation, children are indexed for retrieval.
    """
    groups: list[tuple[list[ParsedBlock], list[str]]] = []
    current: list[ParsedBlock] = []
    current_heading: list[str] = []
    heading_stack: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal current
        if current:
            groups.append((current, list(current_heading)))
            current = []

    for block in parsed.blocks:
        if block.heading_level > 0:
            if current and all(b.heading_level > 0 for b in current):
                current = []
            else:
                flush()
            while heading_stack and heading_stack[-1][0] >= block.heading_level:
                heading_stack.pop()
            heading_stack.append((block.heading_level, block.text.strip()))
            current_heading = [text for _, text in heading_stack]
            current.append(block)
            # A heading immediately followed by another heading should still merge.
            continue

        if block.block_type == "table":
            # A heading-only group is not useful as a standalone parent; the
            # heading is already carried in heading_path.
            if current and all(b.heading_level > 0 for b in current):
                current = []
            else:
                flush()
            groups.append(([block], list(current_heading)))
            continue

        current_size = sum(len(b.text) for b in current)
        if current and current_size + len(block.text) > parent_target:
            flush()
        current.append(block)
    flush()

    chunks: list[ChunkDraft] = []
    parent_ordinal = 0
    child_ordinal = 0
    for blocks, heading_path in groups:
        heading_path = sanitize_heading_path(heading_path)
        # PDF text layers occasionally carry NUL bytes (seen in DB37/T feed
        # standards); Postgres rejects them on insert, which failed the whole
        # document. Strip them at the single point where text enters.
        content = _join_blocks(blocks).replace("\x00", "").strip()
        if not content:
            continue
        locations = _merge_locations(blocks)
        block_type = "table" if all(b.block_type == "table" for b in blocks) else "text"
        page_from = min(b.page for b in blocks)
        page_to = max(b.page for b in blocks)
        parent_id = uuid.uuid5(
            CHUNK_NAMESPACE,
            f"{version_id}:parent:{parent_ordinal}:{_sha(content)[:16]}",
        )
        chunks.append(
            ChunkDraft(
                id=parent_id,
                parent_id=None,
                role="parent",
                ordinal=parent_ordinal,
                content=content,
                heading_path=heading_path,
                block_type=block_type,
                page_from=page_from,
                page_to=page_to,
                token_count=_token_count(content),
                locations=locations,
            )
        )
        parent_ordinal += 1

        if block_type == "table":
            children = _split_table(content, child_target, overlap)
        else:
            children = _split_text(content, child_target, overlap)

        for child in children:
            child = child.strip()
            if not child:
                continue
            chunks.append(
                ChunkDraft(
                    id=uuid.uuid5(
                        CHUNK_NAMESPACE,
                        f"{version_id}:child:{child_ordinal}:{_sha(child)[:16]}",
                    ),
                    parent_id=parent_id,
                    role="child",
                    ordinal=child_ordinal,
                    content=child,
                    heading_path=heading_path,
                    block_type=block_type,
                    page_from=page_from,
                    page_to=page_to,
                    token_count=_token_count(child),
                    locations=locations,
                )
            )
            child_ordinal += 1

    return chunks
