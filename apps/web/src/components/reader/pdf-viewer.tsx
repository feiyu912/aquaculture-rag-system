"use client";

import * as React from "react";
import type { PdfDocumentProxy, PdfPageProxy, PdfViewport } from "@/lib/pdf/loader";
import { FileWarning, Loader2 } from "lucide-react";

import { bboxToViewportRect } from "@/lib/pdf/coords";
import { cn } from "@/lib/utils";

export interface PdfHighlight {
  page: number;
  bbox: [number, number, number, number];
  label?: string;
}

interface PageEntry {
  pageNumber: number;
  /** Unscaled CSS pixel size of the page. */
  width: number;
  height: number;
}

export function PdfViewer({
  pdf,
  scale,
  highlight,
  className,
  onVisiblePageChange,
  onPageRendered,
}: {
  pdf: PdfDocumentProxy;
  scale: number;
  highlight?: PdfHighlight | null;
  className?: string;
  onVisiblePageChange?: (page: number) => void;
  onPageRendered?: (page: number, viewport: PdfViewport) => void;
}) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const canvasRefs = React.useRef(new Map<number, HTMLCanvasElement>());
  const pageRefs = React.useRef(new Map<number, HTMLDivElement>());
  const renderTokenRef = React.useRef(0);
  const renderedRef = React.useRef(new Set<number>());
  const renderingRef = React.useRef(new Set<number>());
  const viewportRef = React.useRef(new Map<number, PdfViewport>());
  const observerRef = React.useRef<IntersectionObserver | null>(null);

  const [pages, setPages] = React.useState<PageEntry[]>([]);
  const [rendering, setRendering] = React.useState<Set<number>>(new Set());
  const [failed, setFailed] = React.useState<Set<number>>(new Set());
  const [activePage, setActivePage] = React.useState(1);

  // Collect the intrinsic page sizes once per document.
  React.useEffect(() => {
    let cancelled = false;
    const entries: PageEntry[] = [];

    const run = async () => {
      for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
        const page = await pdf.getPage(pageNumber);
        const viewport = page.getViewport({ scale: 1 });
        entries.push({ pageNumber, width: viewport.width, height: viewport.height });
      }
      if (!cancelled) setPages(entries);
    };

    void run().catch(() => {
      if (!cancelled) setFailed(new Set([1]));
    });

    return () => {
      cancelled = true;
    };
  }, [pdf]);

  const renderPage = React.useCallback(
    async (pageNumber: number) => {
      if (renderedRef.current.has(pageNumber) || renderingRef.current.has(pageNumber)) return;
      const canvas = canvasRefs.current.get(pageNumber);
      if (!canvas) return;

      const token = renderTokenRef.current;
      renderingRef.current.add(pageNumber);
      setRendering((prev) => new Set(prev).add(pageNumber));

      try {
        const page: PdfPageProxy = await pdf.getPage(pageNumber);
        const viewport = page.getViewport({ scale });
        const context = canvas.getContext("2d");
        if (!context) return;

        const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;

        await page.render({
          canvas,
          canvasContext: context,
          viewport,
          transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
        }).promise;

        if (token !== renderTokenRef.current) return;
        viewportRef.current.set(pageNumber, viewport);
        renderedRef.current.add(pageNumber);
        setFailed((prev) => {
          if (!prev.has(pageNumber)) return prev;
          const next = new Set(prev);
          next.delete(pageNumber);
          return next;
        });
        onPageRendered?.(pageNumber, viewport);
      } catch (error) {
        if ((error as Error)?.name === "RenderingCancelledException") return;
        setFailed((prev) => new Set(prev).add(pageNumber));
      } finally {
        renderingRef.current.delete(pageNumber);
        setRendering((prev) => {
          const next = new Set(prev);
          next.delete(pageNumber);
          return next;
        });
      }
    },
    [pdf, scale, onPageRendered],
  );

  // Re-render every page when the zoom level changes.
  React.useEffect(() => {
    renderTokenRef.current += 1;
    renderedRef.current.clear();
    viewportRef.current.clear();
    renderingRef.current.clear();
    setRendering(new Set());
    // Rendering is kicked off by the intersection observer below.
  }, [scale]);

  // Always render the highlighted page, even when it is far outside the
  // viewport, so the highlight can be positioned and scrolled to.
  React.useEffect(() => {
    if (!highlight || pages.length === 0) return;
    void renderPage(highlight.page);
  }, [highlight, renderPage, pages.length]);

  // Lazily render pages as they scroll into view.
  React.useEffect(() => {
    if (pages.length === 0) return;
    const root = containerRef.current;
    if (!root) return;

    observerRef.current?.disconnect();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const pageNumber = Number((entry.target as HTMLElement).dataset.page);
          if (Number.isFinite(pageNumber)) void renderPage(pageNumber);
        }
      },
      { root, rootMargin: "600px 0px" },
    );

    for (const [pageNumber, node] of pageRefs.current) {
      if (node) observer.observe(node);
    }
    observerRef.current = observer;

    return () => observer.disconnect();
  }, [pages, renderPage]);

  // Track the page currently in the middle of the viewport.
  React.useEffect(() => {
    const root = containerRef.current;
    if (!root) return;

    const onScroll = () => {
      const rootRect = root.getBoundingClientRect();
      const middle = rootRect.top + rootRect.height / 2;
      let best = activePage;
      let bestDistance = Number.POSITIVE_INFINITY;

      for (const [pageNumber, node] of pageRefs.current) {
        if (!node) continue;
        const rect = node.getBoundingClientRect();
        if (rect.bottom < rootRect.top || rect.top > rootRect.bottom) continue;
        const distance = Math.abs(rect.top + rect.height / 2 - middle);
        if (distance < bestDistance) {
          bestDistance = distance;
          best = pageNumber;
        }
      }

      if (best !== activePage) {
        setActivePage(best);
        onVisiblePageChange?.(best);
      }
    };

    root.addEventListener("scroll", onScroll, { passive: true });
    return () => root.removeEventListener("scroll", onScroll);
  }, [activePage, onVisiblePageChange, pages]);

  const highlightRect = React.useMemo(() => {
    if (!highlight) return null;
    const viewport = viewportRef.current.get(highlight.page);
    if (!viewport) return null;
    return bboxToViewportRect({ bbox: highlight.bbox }, viewport);
  }, [highlight, rendering]);

  // Bring the highlighted region into view once its page has been rendered.
  const scrolledRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!highlight || !highlightRect) return;
    const key = `${highlight.page}-${highlight.bbox.join(",")}`;
    if (scrolledRef.current === key) return;

    const container = containerRef.current;
    const pageNode = pageRefs.current.get(highlight.page);
    if (!container || !pageNode) return;

    scrolledRef.current = key;
    const pageRect = pageNode.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    const offsetInPage = pageRect.top - containerRect.top + container.scrollTop;
    const target = offsetInPage + highlightRect.top - container.clientHeight * 0.35;

    container.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
  }, [highlight, highlightRect, rendering, pages.length]);

  return (
    <div
      ref={containerRef}
      className={cn(
        "h-full overflow-auto bg-instrument px-4 py-6 sm:px-8",
        className,
      )}
    >
      <div className="mx-auto flex w-fit flex-col items-center gap-6">
        {pages.map((entry) => {
          const width = Math.round(entry.width * scale);
          const height = Math.round(entry.height * scale);
          const isHighlighted = highlight?.page === entry.pageNumber;

          return (
            <div
              key={entry.pageNumber}
              data-page={entry.pageNumber}
              ref={(node) => {
                if (node) pageRefs.current.set(entry.pageNumber, node);
                else pageRefs.current.delete(entry.pageNumber);
              }}
              className="relative"
            >
              <div
                className={cn(
                  "relative bg-white shadow-[0_10px_40px_-12px_rgba(0,0,0,0.6)] transition-shadow duration-200",
                  isHighlighted && "ring-2 ring-primary-400 ring-offset-2 ring-offset-instrument",
                )}
                style={{ width, height }}
              >
                <canvas
                  ref={(node) => {
                    if (node) canvasRefs.current.set(entry.pageNumber, node);
                    else canvasRefs.current.delete(entry.pageNumber);
                  }}
                  className="block"
                />

                {isHighlighted && highlightRect && (
                  <div
                    className="pointer-events-none absolute rounded-[3px] bg-primary-400/28 ring-2 ring-primary-500/80"
                    style={{
                      left: highlightRect.left,
                      top: highlightRect.top,
                      width: highlightRect.width,
                      height: highlightRect.height,
                    }}
                  />
                )}

                {rendering.has(entry.pageNumber) && (
                  <div className="absolute inset-0 flex items-center justify-center bg-white/70">
                    <Loader2 className="size-5 animate-spin text-muted-foreground" />
                  </div>
                )}

                {failed.has(entry.pageNumber) && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-white text-muted-foreground">
                    <FileWarning className="size-5" />
                    <span className="text-[12px]">此页渲染失败</span>
                  </div>
                )}
              </div>

              <span className="mt-2 block text-center text-[11px] tabular-nums text-instrument-muted">
                {entry.pageNumber}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
