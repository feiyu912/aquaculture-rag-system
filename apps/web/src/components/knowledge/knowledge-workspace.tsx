"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Database,
  FileStack,
  Layers,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import { DocumentDetailDialog } from "@/components/knowledge/document-detail-dialog";
import { NewVersionDialog } from "@/components/knowledge/new-version-dialog";
import { QaLibraryPanel } from "@/components/knowledge/qa-library-panel";
import { DocumentTable, StatCard } from "@/components/knowledge/document-table";
import type { KnowledgeFilters } from "@/components/knowledge/knowledge-filter-panel";
import {
  UploadDropzone,
  UploadQueue,
  type UploadItem,
} from "@/components/knowledge/upload-dropzone";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDocumentMutations } from "@/hooks/use-documents";
import { useCatalogFacets, useCatalogStats, useDocumentPage } from "@/hooks/use-management";
import { documentsApi } from "@/lib/api/documents";
import type { ManagedDocument } from "@/lib/api/types";
import { cn } from "@/lib/utils";

let uploadCounter = 0;

function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function isFiltered(filters: KnowledgeFilters): boolean {
  return (
    filters.query.trim() !== "" ||
    filters.status !== null ||
    filters.published !== "all" ||
    filters.technicalReview !== null ||
    filters.domainReview !== null ||
    filters.documentType !== null ||
    filters.sourceType !== null ||
    filters.authorityLevel !== null ||
    filters.language !== null ||
    filters.species !== null ||
    filters.category !== null ||
    filters.license !== null
  );
}

export function KnowledgeWorkspace({
  filters,
  onFiltersChange,
  tab,
  onTabChange,
}: {
  filters: KnowledgeFilters;
  onFiltersChange: (filters: KnowledgeFilters) => void;
  tab: "documents" | "qa";
  onTabChange: (tab: "documents" | "qa") => void;
}) {
  const router = useRouter();
  const debouncedQuery = useDebounced(filters.query.trim());
  const offset = (filters.page - 1) * filters.pageSize;
  const publishedParam: "true" | "false" | undefined =
    filters.published === "published"
      ? "true"
      : filters.published === "unpublished"
        ? "false"
        : undefined;
  const pageQuery = React.useMemo(
    () => ({
      q: debouncedQuery || undefined,
      status: filters.status ?? undefined,
      published: publishedParam,
      technical_review: filters.technicalReview ?? undefined,
      domain_review: filters.domainReview ?? undefined,
      document_type: filters.documentType ?? undefined,
      source_type: filters.sourceType ?? undefined,
      authority_level: filters.authorityLevel ?? undefined,
      language: filters.language ?? undefined,
      species: filters.species ?? undefined,
      category: filters.category ?? undefined,
      license: filters.license ?? undefined,
      sort: filters.sort,
      limit: filters.pageSize,
      offset,
    }),
    [debouncedQuery, filters, offset, publishedParam],
  );
  const { data: page, isLoading, isError, error, refetch, isFetching } =
    useDocumentPage(pageQuery);
  const { data: stats } = useCatalogStats();
  const { data: facets } = useCatalogFacets();
  const { upload, invalidate } = useDocumentMutations();

  const [queue, setQueue] = React.useState<UploadItem[]>([]);
  const [detailId, setDetailId] = React.useState<string | null>(null);
  const [title, setTitle] = React.useState("");
  const [category, setCategory] = React.useState("未分类");
  const [species, setSpecies] = React.useState("");
  const [versionTarget, setVersionTarget] = React.useState<ManagedDocument | null>(null);

  const categories = React.useMemo(() => {
    const values = new Set<string>();
    for (const item of facets?.category ?? []) values.add(item.value);
    if (values.size === 0) values.add("未分类");
    return Array.from(values);
  }, [facets]);

  React.useEffect(() => {
    const pending = queue.filter((item) => item.status === "processing" && item.jobId);
    if (pending.length === 0) return;

    const timer = setInterval(async () => {
      for (const item of pending) {
        if (!item.jobId) continue;
        try {
          const job = await documentsApi.job(item.jobId);
          setQueue((prev) =>
            prev.map((entry) =>
              entry.id === item.id
                ? {
                    ...entry,
                    status:
                      job.status === "succeeded"
                        ? "succeeded"
                        : job.status === "failed"
                          ? "failed"
                          : "processing",
                    progress: job.progress ?? 0,
                    stage: job.current_stage,
                    error: job.error_message ?? job.error_code ?? undefined,
                  }
                : entry,
            ),
          );
          if (job.status === "succeeded" || job.status === "failed") {
            invalidate();
          }
        } catch {
          /* keep polling */
        }
      }
    }, 1500);

    return () => clearInterval(timer);
  }, [queue, invalidate]);

  const handleFiles = async (files: File[]) => {
    for (const file of files) {
      uploadCounter += 1;
      const itemId = `upload-${uploadCounter}`;
      const item: UploadItem = {
        id: itemId,
        fileName: file.name,
        fileSize: file.size,
        status: "uploading",
        progress: 0,
      };
      setQueue((prev) => [...prev, item]);

      const form = new FormData();
      form.append("file", file);
      if (title.trim()) form.append("title", title.trim());
      if (category.trim()) form.append("category", category.trim());
      if (species.trim()) form.append("species", species.trim());

      try {
        const result = await upload.mutateAsync(form);
        setQueue((prev) =>
          prev.map((entry) =>
            entry.id === itemId
              ? { ...entry, status: "processing", jobId: result.job_id, documentId: result.document_id }
              : entry,
          ),
        );
        invalidate();
      } catch (uploadError) {
        setQueue((prev) =>
          prev.map((entry) =>
            entry.id === itemId
              ? {
                  ...entry,
                  status: "failed",
                  error: uploadError instanceof Error ? uploadError.message : "上传失败",
                }
              : entry,
          ),
        );
      }
    }
    setTitle("");
  };

  const goToPage = (pageNumber: number) => {
    onFiltersChange({ ...filters, page: Math.max(1, pageNumber) });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const total = page?.total ?? 0;
  const pages = Math.max(1, page?.pages ?? 1);
  const currentPage = page?.page ?? filters.page;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = total === 0 ? 0 : offset + (page?.items.length ?? 0);

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="scroll-contain min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1180px] px-4 py-6 sm:px-6 sm:py-8">
            <Tabs value={tab} onValueChange={(value) => onTabChange(value as "documents" | "qa")}>
              <TabsList className="mb-5">
                <TabsTrigger value="documents">文献资料</TabsTrigger>
                <TabsTrigger value="qa">问答数据</TabsTrigger>
              </TabsList>
            </Tabs>
            {tab === "qa" ? (
              <QaLibraryPanel />
            ) : (
              <>
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <StatCard
                label="有效资料"
                value={stats?.documents.independent_sources.effective ?? "—"}
                hint="去重后 · 已发布 + 当前版本"
                icon={ShieldCheck}
                tone="success"
              />
              <StatCard
                label="在线可检索"
                value={stats?.documents.retrievable ?? "—"}
                hint={`active + verified + 当前版本已就绪；集合共 ${stats?.chunks.current_active.total ?? "—"} 块`}
                icon={Database}
              />
              <StatCard
                label="待审核"
                value={stats?.documents.staging ?? "—"}
                hint={`其中 ${stats?.documents.independent_sources.staging_with_current_version ?? 0} 个已有解析版本，仍不发布`}
                icon={FileStack}
                tone="warning"
              />
              <StatCard
                label="全库父 / 子块"
                value={
                  stats
                    ? `${stats.chunks.all_versions.parent} / ${stats.chunks.all_versions.child}`
                    : "—"
                }
                hint={`${stats?.versions.total ?? 0} 个版本 · ${stats?.versions.documents_with_multiple_versions ?? 0} 个多版本文档`}
                icon={Layers}
              />
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 rounded-xl border border-border bg-surface px-3.5 py-2 text-[11px] text-subtle-foreground">
              <span>
                全库记录 {stats?.documents.records_including_deleted ?? "—"}，其中删除{" "}
                {stats?.documents.deleted ?? "—"}（不计入有效规模）
              </span>
              <span>已发布 {stats?.documents.published ?? "—"}</span>
              <span>待审核 {stats?.documents.staging ?? "—"}</span>
              <span>
                重复来源归并{" "}
                {stats?.documents.independent_sources.duplicate_or_repeated_records ?? "—"} 条
              </span>
              <span>
                有效文档版本 {stats?.versions.live_total ?? "—"}（全库{" "}
                {stats?.versions.total ?? "—"}）
              </span>
            </div>

            <section className="mt-6">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-[14px] font-semibold text-foreground">上传资料</h2>
              </div>

              <UploadDropzone onFiles={handleFiles} disabled={upload.isPending} />

              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <div>
                  <Label htmlFor="kb-title" className="text-[11.5px]">
                    标题（可选，默认取文件名）
                  </Label>
                  <Input
                    id="kb-title"
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="例如：南美白对虾养殖技术规范"
                    className="mt-1.5 h-8 text-[12.5px]"
                  />
                </div>
                <div>
                  <Label htmlFor="kb-category" className="text-[11.5px]">
                    分类
                  </Label>
                  <Input
                    id="kb-category"
                    value={category}
                    onChange={(event) => setCategory(event.target.value)}
                    list="kb-categories"
                    className="mt-1.5 h-8 text-[12.5px]"
                  />
                  <datalist id="kb-categories">
                    {categories.map((item) => (
                      <option key={item} value={item} />
                    ))}
                  </datalist>
                </div>
                <div>
                  <Label htmlFor="kb-species" className="text-[11.5px]">
                    适用品种（逗号分隔，留空 = 通用）
                  </Label>
                  <Input
                    id="kb-species"
                    value={species}
                    onChange={(event) => setSpecies(event.target.value)}
                    placeholder="例如：中华绒螯蟹、凡纳滨对虾"
                    className="mt-1.5 h-8 text-[12.5px]"
                  />
                </div>
              </div>

              {queue.length > 0 && (
                <div className="mt-4">
                  <UploadQueue
                    items={queue}
                    onDismiss={(id) => setQueue((prev) => prev.filter((entry) => entry.id !== id))}
                  />
                </div>
              )}
            </section>

            <section className="mt-8">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-[14px] font-semibold text-foreground">
                  文档列表
                  <span className="ml-2 text-[12px] font-normal text-subtle-foreground">
                    {total} 条 · 第 {showingFrom}–{showingTo} 条
                  </span>
                </h2>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    void refetch();
                    invalidate();
                  }}
                  disabled={isFetching}
                >
                  {isFetching ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="size-3.5" />
                  )}
                  刷新
                </Button>
              </div>

              {isError ? (
                <div className="flex items-start gap-3 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3.5 text-[12.5px] text-danger">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  <div className="min-w-0">
                    <p className="font-medium">文档列表加载失败</p>
                    <p className="mt-0.5 break-words text-danger/80">
                      {error instanceof Error ? error.message : "管理接口不可用"}
                    </p>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-2"
                      onClick={() => void refetch()}
                    >
                      重试
                    </Button>
                  </div>
                </div>
              ) : (
                <DocumentTable
                  documents={page?.items ?? []}
                  loading={isLoading}
                  filtered={isFiltered(filters)}
                  actions={{
                    onOpen: (item) => setDetailId(item.id),
                    onNewVersion: (item) => setVersionTarget(item),
                    onRollback: (item) => setDetailId(item.id),
                    onDelete: (item) => setDetailId(item.id),
                    onRead: (item) =>
                      item.source_type === "html"
                        ? router.push(`/source?document_id=${item.id}`)
                        : router.push(
                            `/reader?document_id=${item.id}${
                              item.current_version_id
                                ? `&version_id=${item.current_version_id}`
                                : ""
                            }`,
                          ),
                  }}
                />
              )}

              {total > 0 ? (
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
                    <span>每页</span>
                    <select
                      aria-label="每页条数"
                      className="h-7 rounded-md border border-border bg-surface px-1.5 text-[11.5px]"
                      value={filters.pageSize}
                      onChange={(event) =>
                        onFiltersChange({
                          ...filters,
                          pageSize: Number(event.target.value),
                          page: 1,
                        })
                      }
                    >
                      {[10, 25, 50, 100].map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </select>
                    <span className="tabular-nums">
                      第 {currentPage} / {pages} 页
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!page?.has_prev || isFetching}
                      onClick={() => goToPage(currentPage - 1)}
                    >
                      <ChevronLeft className="size-3.5" />
                      上一页
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!page?.has_next || isFetching}
                      onClick={() => goToPage(currentPage + 1)}
                    >
                      下一页
                      <ChevronRight className="size-3.5" />
                    </Button>
                  </div>
                </div>
              ) : null}
            </section>
              </>
            )}
          </div>
        </div>
      </div>

      <DocumentDetailDialog
        documentId={detailId}
        onClose={() => setDetailId(null)}
        onDeleted={() => invalidate()}
        onRead={(documentId, versionId, mediaType) =>
          mediaType === "html"
            ? router.push(`/source?document_id=${documentId}&version_id=${versionId}`)
            : router.push(`/reader?document_id=${documentId}&version_id=${versionId}`)
        }
      />

      <NewVersionDialog
        document={versionTarget}
        onClose={() => {
          setVersionTarget(null);
          invalidate();
        }}
      />
    </div>
  );
}
