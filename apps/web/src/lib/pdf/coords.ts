import type { BBoxLocation } from "@/lib/api/types";

/**
 * Transform between the backend's canonical bbox and PDF.js viewport
 * coordinates.
 *
 * Backend contract (`apps/api/app/ingestion/parser.py`):
 *   - `bbox` is `[x0, y0, x1, y1]` in PDF **points**
 *   - `x` is measured from the **left** of the CropBox
 *   - `y` is measured from the **top** of the CropBox (the origin is flipped
 *     to bottom-left and then normalised against `crop.y1`)
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
  const [viewX0, , viewX1, viewY1] = viewport.viewBox;
  const [x0, y0, x1, y1] = location.bbox;

  // Crop-relative -> absolute PDF user space.
  const absLeft = viewX0 + x0;
  const absRight = viewX0 + x1;
  const absTop = viewY1 - y0;
  const absBottom = viewY1 - y1;

  const [px0, py0] = viewport.convertToViewportPoint(absLeft, absTop);
  const [px1, py1] = viewport.convertToViewportPoint(absRight, absBottom);

  return {
    left: Math.min(px0, px1),
    top: Math.min(py0, py1),
    width: Math.abs(px1 - px0),
    height: Math.abs(py1 - py0),
  };
}

/** Parse the compact `bbox=x0,y0,x1,y1` query parameter used by deep links. */
export function parseBBoxParam(value: string | null): [number, number, number, number] | null {
  if (!value) return null;
  const parts = value.split(",").map((part) => Number.parseFloat(part));
  if (parts.length !== 4 || parts.some((part) => !Number.isFinite(part))) return null;
  return parts as [number, number, number, number];
}
