"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  FileStack,
  FileText,
  Layers,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";

import { DocumentDetailDialog } from "@/components/knowledge/document-detail-dialog";
import { DocumentTable, StatCard } from "@/components/knowledge/document-table";
import {
  EMPTY_FILTERS,
  type KnowledgeFilters,
} from "@/components/knowledge/knowledge-filter-panel";
import {
  UploadDropzone,
  UploadQueue,
  type UploadItem,
} from "@/components/knowledge/upload-dropzone";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useDocumentMutations, useDocuments } from "@/hooks/use-documents";
import { documentsApi } from "@/lib/api/documents";
import type { DocumentOut } from "@/lib/api/types";

let uploadCounter = 0;

export function KnowledgeWorkspace({
  filters,
  onFiltersChange,
}: {
  filters: KnowledgeFilters;
  onFiltersChange: (filters: KnowledgeFilters) => void;
}) {
  const router = useRouter();
  const { data: documents, isLoading, refetch, isFetching } = useDocuments();
  const { upload, addVersion, invalidate } = useDocumentMutations();
  const { data: speciesOptions } = useQuery({
    queryKey: ["species"],
    queryFn: documentsApi.species,
    staleTime: 60_000,
  });

  const [queue, setQueue] = React.useState<UploadItem[]>([]);
  const [detailId, setDetailId] = React.useState<string | null>(null);
  const [title, setTitle] = React.useState("");
  const [category, setCategory] = React.useState("未分类");
  const [species, setSpecies] = React.useState("");
  const [pendingVersionFor, setPendingVersionFor] = React.useState<DocumentOut | null>(null);

  const watchRef = React.useRef(new Map<string, string>());

  // Poll every ingest job that is still in the queue.
  React.useEffect(() => {
    const pending = queue.filter(
      (item) => item.status === "processing" && item.jobId,
    );
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
                    status: job.status === "succeeded" ? "succeeded" : job.status === "failed" ? "failed" : "processing",
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

  const categories = React.useMemo(() => {
    const set = new Set<string>();
    for (const document of documents ?? []) set.add(document.category);
    set.add("未分类");
    return Array.from(set);
  }, [documents]);

  const filtered = React.useMemo(() => {
    const keyword = filters.query.trim().toLowerCase();
    return (documents ?? []).filter((document) => {
      if (keyword && !document.title.toLowerCase().includes(keyword)) return false;
      if (filters.category && document.category !== filters.category) return false;
      if (
        filters.species &&
        !(document.species ?? []).includes(filters.species)
      ) {
        return false;
      }
      if (filters.status === "active" && !document.current_version_id) return false;
      if (filters.status === "inactive" && document.current_version_id) return false;
      return true;
    });
  }, [documents, filters]);

  const stats = React.useMemo(() => {
    const list = documents ?? [];
    return {
      total: list.length,
      active: list.filter((document) => document.current_version_id).length,
      pages: list.reduce((sum, document) => sum + (document.page_count ?? 0), 0),
      species: new Set(list.flatMap((document) => document.species ?? [])).size,
    };
  }, [documents]);

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
      if (pendingVersionFor) {
        form.append("file", file);
        try {
          const result = await addVersion.mutateAsync({
            documentId: pendingVersionFor.id,
            form,
          });
          setQueue((prev) =>
            prev.map((entry) =>
              entry.id === itemId
                ? { ...entry, status: "processing", jobId: result.job_id, documentId: result.document_id }
                : entry,
            ),
          );
          toast.success("新版本已入队", { description: "解析成功后才切换生效版本" });
        } catch (error) {
          setQueue((prev) =>
            prev.map((entry) =>
              entry.id === itemId
                ? {
                    ...entry,
                    status: "failed",
                    error:
                      error instanceof Error ? error.message : "上传失败",
                  }
                : entry,
            ),
          );
        } finally {
          setPendingVersionFor(null);
        }
        continue;
      }

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
      } catch (error) {
        setQueue((prev) =>
          prev.map((entry) =>
            entry.id === itemId
              ? {
                  ...entry,
                  status: "failed",
                  error: error instanceof Error ? error.message : "上传失败",
                }
              : entry,
          ),
        );
      }
    }
    setTitle("");
  };

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1180px] px-4 py-6 sm:px-6 sm:py-8">
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <StatCard
                label="文档总数"
                value={stats.total}
                hint={`共 ${stats.pages} 页已索引`}
                icon={FileText}
              />
              <StatCard
                label="生效版本"
                value={stats.active}
                hint="可被检索与引用"
                icon={FileStack}
                tone="success"
              />
              <StatCard
                label="覆盖品种"
                value={stats.species}
                hint="文档级品种标注"
                icon={Layers}
              />
              <StatCard
                label="当前集合"
                value="BGE-M3"
                hint="kb_chunks_bge_m3_v1"
                icon={BookOpen}
              />
            </div>

            <section className="mt-6">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-[14px] font-semibold text-foreground">上传资料</h2>
                {pendingVersionFor && (
                  <span className="rounded-full bg-warning-soft px-2.5 py-1 text-[11.5px] font-medium text-warning">
                    正在为「{pendingVersionFor.title}」上传新版本
                  </span>
                )}
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
                    onDismiss={(id) =>
                      setQueue((prev) => prev.filter((entry) => entry.id !== id))
                    }
                  />
                </div>
              )}
            </section>

            <section className="mt-8">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 className="text-[14px] font-semibold text-foreground">
                  文档列表
                  <span className="ml-2 text-[12px] font-normal text-subtle-foreground">
                    {filtered.length} / {documents?.length ?? 0}
                  </span>
                </h2>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void refetch()}
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

              <DocumentTable
                documents={filtered}
                loading={isLoading}
                actions={{
                  onOpen: (item) => setDetailId(item.id),
                  onNewVersion: (item) => {
                    setPendingVersionFor(item);
                    toast.info("请选择新的 PDF 文件", {
                      description: `将作为「${item.title}」的新版本上传`,
                    });
                    window
                      .document
                      .querySelector<HTMLInputElement>("#kb-title")
                      ?.scrollIntoView({ behavior: "smooth", block: "center" });
                  },
                  onRollback: (item) => setDetailId(item.id),
                  onDelete: (item) => setDetailId(item.id),
                  onRead: (item) =>
                    router.push(
                      `/reader?document_id=${item.id}${
                        item.current_version_id
                          ? `&version_id=${item.current_version_id}`
                          : ""
                      }`,
                    ),
                }}
              />
            </section>
          </div>
        </div>
      </div>

      <DocumentDetailDialog
        documentId={detailId}
        onClose={() => setDetailId(null)}
        onDeleted={() => invalidate()}
      />
    </div>
  );
}
