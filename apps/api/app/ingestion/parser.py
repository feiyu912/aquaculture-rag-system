from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pymupdf

HEADING_RE = re.compile(
    r"^(第[一二三四五六七八九十百]+[章节篇]|[一二三四五六七八九十]+、|"
    r"\d{1,2}(?:\.\d{1,2}){1,3}\s*[\u4e00-\u9fff]|"
    r"\d{1,2}\s*[\u4e00-\u9fff])"
)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    if CJK_RE.search(text):
        text = re.sub(r"[ \t]*\n[ \t]*", "", text)
    else:
        text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _heading_level(text: str, font_size: float | None, body_size: float) -> int:
    """Return 0 for body text, 1..3 for heading levels."""
    if len(text) > 60 or not text:
        return 0
    if HEADING_RE.match(text):
        if re.match(r"^第[一二三四五六七八九十百]+[章节篇]", text):
            return 1
        if re.match(r"^\d+\.\d+", text):
            return 3
        return 2
    if font_size and body_size and font_size >= body_size * 1.7:
        return 1
    if (
        font_size
        and body_size
        and font_size >= body_size * 1.25
        and not text.endswith(("。", "；", "，"))
    ):
        return 3 if text.endswith("：") else 2
    return 0


def _overlap_ratio(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    return inter / area


@dataclass(slots=True)
class ParsedBlock:
    page: int
    bbox: list[float]  # canonical: PDF points, origin bottom-left, CropBox-relative, unrotated
    text: str
    page_width: float
    page_height: float
    block_type: str = "text"
    heading_level: int = 0
    font_size: float | None = None
    rotation: int = 0

    def location(self) -> dict:
        return {
            "page": self.page,
            "bbox": [round(v, 2) for v in self.bbox],
            "coordinate_system": "pdf_points",
            "origin": "bottom-left",
            "rotation": self.rotation,
            "page_width": round(self.page_width, 2),
            "page_height": round(self.page_height, 2),
        }


@dataclass(slots=True)
class ParsedDocument:
    page_count: int
    blocks: list[ParsedBlock] = field(default_factory=list)
    parser_name: str = "pymupdf"
    parser_version: str = ""


class DocumentParser(Protocol):
    name: str

    def parse(self, path: Path) -> ParsedDocument: ...


class PyMuPDFParser:
    """Default parser for text PDFs.

    MinerU will replace this for scanned/complex layouts. The normalized block
    model and the coordinate convention stay the same, so downstream code does
    not depend on the parser.
    """

    name = "pymupdf"

    def parse(self, path: Path) -> ParsedDocument:
        doc = pymupdf.open(path)
        page_count = doc.page_count
        blocks: list[ParsedBlock] = []
        try:
            for page_index, page in enumerate(doc, start=1):
                blocks.extend(self._parse_page(page, page_index))
        finally:
            doc.close()
        return ParsedDocument(
            page_count=page_count,
            blocks=blocks,
            parser_name=self.name,
            parser_version=pymupdf.__version__,
        )

    def _parse_page(self, page: pymupdf.Page, page_index: int) -> list[ParsedBlock]:
        crop = page.cropbox
        width, height = float(crop.width), float(crop.height)
        rotation = int(page.rotation)

        raw = page.get_text("dict")
        body_size = self._body_font_size(raw)
        tables = self._extract_tables(page)
        table_rects = [t["rect"] for t in tables]

        out: list[ParsedBlock] = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            rect = tuple(float(v) for v in block["bbox"])
            if _overlap_ratio(rect, (crop.x0, crop.y0, crop.x1, crop.y1)) < 0.5:
                continue
            # Drop likely running headers/footers; keep long blocks.
            if (
                rect[3] < crop.y0 + height * 0.05 or rect[1] > crop.y1 - height * 0.05
            ) and block.get("lines") is not None:
                text_len = sum(
                    len(s.get("text", "")) for line in block["lines"] for s in line["spans"]
                )
                if text_len < 80:
                    continue
            if any(_overlap_ratio(rect, tr) > 0.3 for tr in table_rects):
                continue

            text_parts: list[str] = []
            sizes: list[float] = []
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                if line_text:
                    text_parts.append(line_text)
                    sizes.extend(float(span.get("size", 0)) for span in line.get("spans", []))
            text = _clean_text("\n".join(text_parts))
            if not text:
                continue
            if len(text) == 1 and text not in "。！？；：，、":
                continue

            max_size = max(sizes) if sizes else None
            level = _heading_level(text, max_size, body_size)
            out.append(
                ParsedBlock(
                    page=page_index,
                    bbox=self._canonical_bbox(rect, crop),
                    text=text,
                    page_width=width,
                    page_height=height,
                    block_type="text",
                    heading_level=level,
                    font_size=max_size,
                    rotation=rotation,
                )
            )

        for table in tables:
            text = table["text"]
            if not text.strip():
                continue
            out.append(
                ParsedBlock(
                    page=page_index,
                    bbox=self._canonical_bbox(table["rect"], crop),
                    text=text,
                    page_width=width,
                    page_height=height,
                    block_type="table",
                    heading_level=0,
                    rotation=rotation,
                )
            )

        # Reading order: top-to-bottom, then left-to-right. bbox is bottom-left origin.
        out.sort(key=lambda b: (-b.bbox[3], b.bbox[0]))
        return out

    @staticmethod
    def _canonical_bbox(rect: tuple[float, float, float, float], crop: pymupdf.Rect) -> list[float]:
        x0, y0, x1, y1 = rect
        return [
            max(0.0, x0 - crop.x0),
            max(0.0, crop.y1 - y1),
            min(float(crop.width), x1 - crop.x0),
            min(float(crop.height), crop.y1 - y0),
        ]

    @staticmethod
    def _body_font_size(raw: dict) -> float:
        sizes: list[float] = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        sizes.append(float(span.get("size", 0)))
        return statistics.median(sizes) if sizes else 10.0

    @staticmethod
    def _extract_tables(page: pymupdf.Page) -> list[dict]:
        try:
            finder = page.find_tables()
        except Exception:
            return []
        tables: list[dict] = []
        for table in getattr(finder, "tables", []):
            try:
                rows = table.extract()
            except Exception:
                continue
            rows = [[(_clean_text(cell or "")) for cell in row] for row in rows]
            rows = [row for row in rows if any(row)]
            if len(rows) < 2:
                continue
            header, body = rows[0], rows[1:]
            lines = [
                "| " + " | ".join(header) + " |",
                "| " + " | ".join("---" for _ in header) + " |",
            ]
            lines.extend("| " + " | ".join(row) + " |" for row in body)
            tables.append({"rect": tuple(float(v) for v in table.bbox), "text": "\n".join(lines)})
        return tables


class MineruParser:
    """Placeholder for the MinerU adapter.

    MinerU output varies by version/backend. When implementing, map its blocks
    into ParsedBlock and convert bboxes with the same canonical convention.
    """

    name = "mineru"

    def parse(self, path: Path) -> ParsedDocument:
        raise NotImplementedError(
            "MinerU adapter is not implemented yet; normalized block model is in app/ingestion/parser.py"
        )
