"""HTML parser that produces the same normalised block model as the PDF parser.

Design notes
------------
* The block model is shared with ``PyMuPDFParser`` so chunking, indexing and
  retrieval do not need a second code path.
* A web block has no page or bbox.  Its ``location`` uses
  ``coordinate_system="web_text"`` with the source URL and a text anchor, which
  is what the frontend needs to jump to the paragraph.
* Headings are recovered from the XML tag (h1-h6) *and* from Chinese numbering
  patterns ("一、", "（一）", "1.2"), because many government pages render
  headings as plain paragraphs.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

import trafilatura

from app.ingestion.parser import HEADING_RE, ParsedBlock, ParsedDocument, _clean_text

WEB_ANCHOR_CHARS = 60
TAG_HEADING_LEVEL = {"h1": 1, "h2": 2, "h3": 2, "h4": 3, "h5": 3, "h6": 3}


class HtmlParseError(ValueError):
    pass


# Site chrome that trafilatura keeps when it sits inside the main container.
# Left in place it becomes a citable "source", so drop it at parse time.
BOILERPLATE_MARKERS = (
    "欢迎您！来到全国水产技术推广总站",
    "无障碍 农芯慧答",
    "相关附件：",
    "主办单位：",
    "京ICP备",
    "Copyright ©",
    "版权所有",
    "网站地图",
)


def _strip_inline_nav(text: str) -> str:
    """Remove site chrome that trafilatura merged into the article block."""
    # Chinese portals repeat the nav chain mid-block, so match anywhere, not
    # only in the first 200 characters.
    if not any(marker in text for marker in BOILERPLATE_MARKERS) and not _NAV_CHAIN.search(text):
        return text
    marker = "当前位置："
    pos = text.find(marker)
    if pos != -1:
        end = text.find("。", pos)
        if end != -1 and len(text) - end > 20:
            return text[end + 1 :].strip()
    for sentence_end in ("。", "\n"):
        cut = text.find(sentence_end)
        if cut != -1 and len(text) - cut > 20:
            return text[cut + 1 :].strip()
    return ""


_NAV_CHAIN = re.compile(r"首页\s*[•·>]|当前位置：|主办单位：|京ICP备|公网安备")


def _drop_boilerplate(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    kept: list[ParsedBlock] = []
    for block in blocks:
        text = _strip_inline_nav(block.text or "")
        if not text:
            continue
        if _NAV_CHAIN.search(text[:160]) and len(text) < 200:
            continue
        if text != block.text:
            block = ParsedBlock(
                text=text,
                heading_level=block.heading_level,
                anchor=block.anchor,
                bbox=block.bbox,
            )
        kept.append(block)
    return kept


def _text_of(element: ElementTree.Element) -> str:
    return "".join(element.itertext())


def _heading_level(tag: str, text: str) -> int:
    if tag in TAG_HEADING_LEVEL:
        return TAG_HEADING_LEVEL[tag]
    cleaned = text.strip()
    if len(cleaned) > 60 or not cleaned:
        return 0
    # "（一）鱼类疾病" is a very common Chinese sub-heading but is not covered
    # by the PDF numbering regex, so it is checked first.
    if re.match(r"^（[一二三四五六七八九十]+）", cleaned):
        return 3
    if re.match(r"^[一二三四五六七八九十]+、", cleaned):
        return 2
    match = HEADING_RE.match(cleaned)
    if match:
        if re.match(r"^第[一二三四五六七八九十百]+[章节篇]", cleaned):
            return 1
        if re.match(r"^\d+\.\d+", cleaned):
            return 3
        return 2
    return 0


def _table_to_markdown(element: ElementTree.Element) -> str:
    rows: list[list[str]] = []
    for row in element.iter("row"):
        cells = [_clean_text(_text_of(cell)) for cell in row.iter("cell")]
        if any(cells):
            rows.append(cells)
    if len(rows) < 2:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    header, body = padded[0], padded[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


class HtmlParser:
    """Extract main content from a saved HTML file.

    ``base_url`` is stored verbatim in every block location so a citation can be
    resolved back to the page it came from.
    """

    name = "trafilatura"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or "").strip() or None

    def parse(self, path: Path) -> ParsedDocument:
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
        xml = trafilatura.extract(
            raw,
            url=self.base_url,
            output_format="xml",
            include_tables=True,
            include_comments=False,
            include_images=False,
            favor_precision=True,
        )
        if not xml:
            raise HtmlParseError("HTML 正文抽取失败：页面可能是 JS 渲染或正文为空")
        return self.parse_xml(xml)

    def parse_xml(self, xml: str) -> ParsedDocument:
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:  # pragma: no cover - defensive
            raise HtmlParseError(f"HTML 结构化输出无法解析: {exc}") from exc

        blocks: list[ParsedBlock] = []
        for element in root.iter():
            tag = element.tag
            if tag == "table":
                text = _table_to_markdown(element)
                if text:
                    blocks.append(self._block(text, block_type="table", level=0))
                continue
            if tag not in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "item"}:
                continue
            text = _clean_text(_text_of(element))
            if not text:
                continue
            blocks.append(
                self._block(text, block_type="text", level=_heading_level(tag, text))
            )

        blocks = _drop_boilerplate(blocks)
        if not blocks:
            raise HtmlParseError("HTML 抽取结果没有可用文本块")
        return ParsedDocument(
            page_count=1,
            blocks=blocks,
            parser_name=self.name,
            parser_version=getattr(trafilatura, "__version__", ""),
        )

    def _block(self, text: str, *, block_type: str, level: int) -> ParsedBlock:
        # A pseudo bbox keeps the shared dataclass contract; the location dict
        # switches to web_text so no consumer mistakes it for PDF points.
        return ParsedBlock(
            page=1,
            bbox=[0.0, 0.0, 0.0, 0.0],
            text=text,
            page_width=0.0,
            page_height=0.0,
            block_type=block_type,
            heading_level=level,
            font_size=None,
            rotation=0,
            url=self.base_url,
            anchor=_anchor(text),
        )


def _anchor(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:WEB_ANCHOR_CHARS]