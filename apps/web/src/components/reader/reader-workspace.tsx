"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BookOpen, Loader2, Search } from "lucide-react";

import { CitationSidebar, type ReaderCitation } from "@/components/reader/citation-sidebar";
import { CitationSidebarDrawer } from "@/components/reader/citation-sidebar-drawer";
import { PdfViewer, type PdfHighlight } from "@/components/reader/pdf-viewer";
import { ReaderToolbar } from "@/components/reader/reader-toolbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { API_BASE_URL } from "@/lib/api/client";
import { documentsApi } from "@/lib/api/documents";
import { fetchPdf, type LoadedDocument } from "@/lib/pdf/loader";
import { cn } from "@/lib/utils";

export function ReaderWorkspace({
  documentId,
  versionId,
  title,
  numPagesHint,
  zoom,
  onZoomChange,
  currentPage,
  onPageChange,
  highlight,
  onHighlight,
  activeCitationId,
  onActiveCitationChange,
  citations,
}: {
  documentId: string | null;
  versionId: string | null;
  title: string;
  numPagesHint: number;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  currentPage: number;
  onPageChange: (page: number) => void;
  highlight: PdfHighlight | null;
  onHighlight: (highlight: PdfHighlight | null) => void;
  activeCitationId: string | null;
  onActiveCitationChange: (id: string | null) => void;
  citations: ReaderCitation[];
}) {
  const router = useRouter();
  const [pdf, setPdf] = React.useState<LoadedDocument | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = React.useState(false);
  const [isWide, setIsWide] = React.useState(true);

  // Fit-to-width: on narrow viewports the page would otherwise be cut off.
  const canvasAreaRef = React.useRef<HTMLDivElement>(null);
  const [areaWidth, setAreaWidth] = React.useState(0);
  const [pageWidth, setPageWidth] = React.useState(0);
  const [autoFit, setAutoFit] = React.useState(true);

  React.useEffect(() => {
    const node = canvasAreaRef.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      setAreaWidth(width);
    });
    observer.observe(node);
    setAreaWidth(node.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, [pdf]);

  const fittedScale = React.useMemo(() => {
    if (!areaWidth || !pageWidth) return null;
    return Math.min(3, Math.max(0.4, Number((areaWidth / pageWidth).toFixed(2))));
  }, [areaWidth, pageWidth]);

  // Manual zoom takes over; the fit only applies until the user zooms.
  const handleZoomChange = React.useCallback(
    (next: number) => {
      setAutoFit(false);
      onZoomChange(next);
    },
    [onZoomChange],
  );

  const handleFitWidth = React.useCallback(() => {
    if (fittedScale) {
      setAutoFit(true);
      onZoomChange(fittedScale);
    }
  }, [fittedScale, onZoomChange]);

  React.useEffect(() => {
    if (!autoFit || !fittedScale) return;
    if (Math.abs(fittedScale - zoom) > 0.01) onZoomChange(fittedScale);
  }, [autoFit, fittedScale, zoom, onZoomChange]);

  // The citation list is a docked column on wide screens and an overlay
  // drawer on narrow ones. The drawer starts closed so it never covers the
  // page the reader just navigated to.
  React.useEffect(() => {
    const media = window.matchMedia("(min-width: 1280px)");
    const apply = () => setIsWide(media.matches);
    apply();
    setSidebarOpen(media.matches);
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);

  React.useEffect(() => {
    if (!documentId) {
      setPdf(null);
      return;
    }
    let cancelled = false;
    setLoadError(null);
    setPdf(null);

    fetchPdf(documentId, versionId)
      .then((loaded) => {
        if (cancelled) return;
        setPdf(loaded);
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setLoadError(error.message);
      });

    return () => {
      cancelled = true;
    };
  }, [documentId, versionId]);

  const handleSelectCitation = (citation: ReaderCitation) => {
    onActiveCitationChange(citation.id);
    if (!citation.bbox) return;
    onHighlight({ page: citation.bbox.page, bbox: citation.bbox.bbox });
    onPageChange(citation.bbox.page);
  };

  if (!documentId) {
    return <DocumentPicker />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ReaderToolbar
        title={title}
        page={currentPage}
        numPages={pdf?.numPages ?? numPagesHint}
        zoom={zoom}
        onZoomChange={handleZoomChange}
        onPageChange={onPageChange}
        onFitWidth={handleFitWidth}
        onToggleCitations={() => setSidebarOpen((prev) => !prev)}
        citationsOpen={sidebarOpen}
        citationCount={citations.length}
        downloadUrl={`${API_BASE_URL}/api/documents/${documentId}/file${
          versionId ? `?version_id=${versionId}` : ""
        }`}
        highlightLabel={highlight ? `高亮 · 第 ${highlight.page} 页` : null}
      />

      {loadError ? (
        <div className="flex flex-1 items-center justify-center p-8">
          <div className="max-w-sm text-center">
            <AlertTriangle className="mx-auto size-6 text-danger" />
            <p className="mt-3 text-[14px] font-semibold text-foreground">无法加载该 PDF</p>
            <p className="mt-1.5 text-[13px] leading-6 text-muted-foreground">{loadError}</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => router.push("/reader")}
            >
              返回文档列表
            </Button>
          </div>
        </div>
      ) : !pdf ? (
        <div className="flex flex-1 items-center justify-center bg-instrument">
          <Loader2 className="size-5 animate-spin text-instrument-muted" />
        </div>
      ) : (
        <>
          <div className="flex min-h-0 flex-1">
            <div className="min-w-0 flex-1" ref={canvasAreaRef}>
              <PdfViewer
                pdf={pdf.doc}
                scale={zoom}
                highlight={highlight}
                targetPage={currentPage}
                onVisiblePageChange={onPageChange}
                onPageRendered={(page, viewport) => {
                  if (page === 1 && viewport.width) setPageWidth(viewport.width / zoom);
                }}
              />
            </div>
            <CitationSidebar
              className={cn("hidden w-[300px] shrink-0 xl:flex", !sidebarOpen && "xl:hidden")}
              citations={citations}
              activeCitationId={activeCitationId}
              onSelect={handleSelectCitation}
              onOpenConversation={(citation) =>
                router.push(`/chat?session_id=${citation.session_id}`)
              }
            />
          </div>

          <CitationSidebarDrawer
            open={sidebarOpen && !isWide}
            citations={citations}
            activeCitationId={activeCitationId}
            onSelect={handleSelectCitation}
            onOpenConversation={(citation) =>
              router.push(`/chat?session_id=${citation.session_id}`)
            }
            onClose={() => setSidebarOpen(false)}
          />
        </>
      )}
    </div>
  );
}

export function DocumentPicker() {
  const router = useRouter();
  const { data: documents, isLoading } = useQuery({
    queryKey: ["documents"],
    queryFn: documentsApi.list,
  });
  const [query, setQuery] = React.useState("");

  const filtered = React.useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return documents ?? [];
    return (documents ?? []).filter((document) =>
      document.title.toLowerCase().includes(keyword),
    );
  }, [documents, query]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[760px] px-4 py-8 sm:px-6">
        <div className="text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary-soft text-primary-soft-fg">
            <BookOpen className="size-6" />
          </div>
          <h2 className="mt-4 text-[19px] font-semibold tracking-[-0.015em] text-foreground">
            文献阅读器
          </h2>
          <p className="mx-auto mt-2 max-w-md text-[13.5px] leading-6 text-muted-foreground">
            选择一份知识库文档查看原文。从智能问答页点击引用，可以直接定位到对应页码并高亮被引用的原文区域。
          </p>
        </div>

        <div className="relative mt-6">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索文档"
            className="h-10 pl-9"
            aria-label="搜索文档"
          />
        </div>

        <ul className="mt-4 space-y-2">
          {isLoading ? (
            <li className="py-8 text-center text-[13px] text-muted-foreground">加载中…</li>
          ) : filtered.length === 0 ? (
            <li className="py-8 text-center text-[13px] text-muted-foreground">
              没有匹配的文档
            </li>
          ) : (
            filtered.map((document) => (
              <li key={document.id}>
                <button
                  type="button"
                  disabled={!document.current_version_id}
                  onClick={() =>
                    router.push(
                      `/reader?document_id=${document.id}&version_id=${document.current_version_id}`,
                    )
                  }
                  className="flex w-full items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-left shadow-xs transition-all duration-200 ease-soft hover:-translate-y-0.5 hover:border-primary-300 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-muted">
                    <BookOpen className="size-4 text-muted-foreground" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13.5px] font-medium text-foreground">
                      {document.title}
                    </span>
                    <span className="mt-0.5 block text-[11.5px] text-subtle-foreground">
                      {document.category} · {document.page_count ?? 0} 页 · v
                      {document.current_version_no ?? "—"}
                    </span>
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
