"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/layout/app-shell";
import { PageList } from "@/components/reader/page-list";
import type { ReaderCitation } from "@/components/reader/citation-sidebar";
import { ReaderWorkspace } from "@/components/reader/reader-workspace";
import type { PdfHighlight } from "@/components/reader/pdf-viewer";
import { API_BASE_URL } from "@/lib/api/client";
import { documentsApi } from "@/lib/api/documents";
import { parseBBoxParam } from "@/lib/pdf/coords";

export function ReaderClient() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const documentId = searchParams.get("document_id");
  const versionId = searchParams.get("version_id");
  const initialPage = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const initialBbox = parseBBoxParam(searchParams.get("bbox"));

  const [zoom, setZoom] = React.useState(1.15);
  const [currentPage, setCurrentPage] = React.useState(
    Number.isFinite(initialPage) && initialPage > 0 ? initialPage : 1,
  );
  const [highlight, setHighlight] = React.useState<PdfHighlight | null>(
    initialBbox && Number.isFinite(initialPage)
      ? { page: initialPage, bbox: initialBbox }
      : null,
  );
  const [activeCitationId, setActiveCitationId] = React.useState<string | null>(null);

  const { data: documents } = useQuery({
    queryKey: ["documents"],
    queryFn: documentsApi.list,
  });

  const { data: citations } = useQuery<ReaderCitation[]>({
    queryKey: ["document-citations", documentId],
    queryFn: () =>
      fetch(`${API_BASE_URL}/api/documents/${documentId}/citations`).then((response) => {
        if (!response.ok) throw new Error("引用列表加载失败");
        return response.json();
      }),
    enabled: Boolean(documentId),
  });

  const document = documents?.find((item) => item.id === documentId);

  const citedPages = React.useMemo(
    () =>
      new Set(
        (citations ?? []).map((citation) => citation.page).filter(Boolean) as number[],
      ),
    [citations],
  );

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", String(page));
    router.replace(`/reader?${params.toString()}`, { scroll: false });
  };

  return (
    <AppShell
      contextLabel="页面"
      context={
        <PageList
          numPages={document?.page_count ?? 0}
          currentPage={currentPage}
          citedPages={citedPages}
          onSelect={handlePageChange}
        />
      }
    >
      <ReaderWorkspace
        documentId={documentId}
        versionId={versionId}
        title={document?.title ?? "PDF 原文"}
        numPagesHint={document?.page_count ?? 0}
        zoom={zoom}
        onZoomChange={setZoom}
        currentPage={currentPage}
        onPageChange={handlePageChange}
        highlight={highlight}
        onHighlight={setHighlight}
        activeCitationId={activeCitationId}
        onActiveCitationChange={setActiveCitationId}
        citations={citations ?? []}
      />
    </AppShell>
  );
}
