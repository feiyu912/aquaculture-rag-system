import type { BBoxLocation } from "@/lib/api/types";

/**
 * Transform between the backend's canonical bbox and PDF.js viewport
 * coordinates.
 *
 * Backend contract (`apps/api/app/ingestion/parser.py`):
 *   - `bbox` is `[x0, y0, x1, y1]` in PDF **points**
 *   - `x` is measured from the **left** of the CropBox
 *   - `y` is measured from the **bottom** of the CropBox — the origin is
 *     bottom-left, exactly like PDF user space (the parser flips PyMuPDF's
 *     top-down rects once, when it writes the record)
 *   - coordinates are CropBox-relative and unrotated
 *
 * PDF.js `PageViewport` maps PDF user space (origin bottom-left, absolute)
 * to viewport pixels (origin top-left, scaled, rotation applied).
 */

export interface ViewportLike {
  viewBox: number[];
  convertToViewportPoint: (x: number, y: number) => number[];
}

export interface ViewportRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function bboxToViewportRect(
  location: Pick<BBoxLocation, "bbox">,
  viewport: ViewportLike,
): ViewportRect {
  const [viewX0, viewY0] = viewport.viewBox;
  const [x0, y0, x1, y1] = location.bbox;

  // Crop-relative -> absolute PDF user space. The stored y is already
  // bottom-up, so it is *not* flipped again here.
  const absLeft = viewX0 + x0;
  const absRight = viewX0 + x1;
  const absBottom = viewY0 + y0;
  const absTop = viewY0 + y1;

  const [px0, py0] = viewport.convertToViewportPoint(absLeft, absTop);
  const [px1, py1] = viewport.convertToViewportPoint(absRight, absBottom);

  return {
    left: Math.min(px0, px1),
    top: Math.min(py0, py1),
    width: Math.abs(px1 - px0),
    height: Math.abs(py1 - py0),
  };
}

/**
 * Keep a highlight inside the rendered page.
 *
 * Citation bboxes come from the parser, but a corrupted or hand-edited record
 * can contain an inverted or absurd rectangle. Clamping keeps the overlay on
 * the page and rejects rectangles that cannot be real.
 */
export function clampToPage(
  rect: ViewportRect,
  pageWidth: number,
  pageHeight: number,
): ViewportRect | null {
  if (!Number.isFinite(rect.left) || !Number.isFinite(rect.top)) return null;
  if (!Number.isFinite(rect.width) || !Number.isFinite(rect.height)) return null;
  if (rect.width <= 0 || rect.height <= 0) return null;

  // A real text block never covers more than the whole page.
  if (rect.width > pageWidth * 1.2 || rect.height > pageHeight * 1.2) return null;

  const left = Math.max(0, Math.min(rect.left, pageWidth));
  const top = Math.max(0, Math.min(rect.top, pageHeight));
  const right = Math.max(left, Math.min(rect.left + rect.width, pageWidth));
  const bottom = Math.max(top, Math.min(rect.top + rect.height, pageHeight));

  const width = right - left;
  const height = bottom - top;
  if (width <= 0 || height <= 0) return null;

  return { left, top, width, height };
}

/** Parse the compact `bbox=x0,y0,x1,y1` query parameter used by deep links. */
export function parseBBoxParam(value: string | null): [number, number, number, number] | null {
  if (!value) return null;
  const parts = value.split(",").map((part) => Number.parseFloat(part));
  if (parts.length !== 4 || parts.some((part) => !Number.isFinite(part))) return null;
  return parts as [number, number, number, number];
}
