"use client";

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  RotateCcw,
  Trash2,
  Upload,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useDocumentDetail, useDocumentMutations } from "@/hooks/use-documents";
import { formatDateTime, truncate } from "@/lib/utils";

const VERSION_STATUS: Record<string, { label: string; variant: "success" | "warning" | "danger" | "neutral" }> = {
  ready: { label: "生效中", variant: "success" },
  archived: { label: "已归档", variant: "neutral" },
  processing: { label: "解析中", variant: "warning" },
  failed: { label: "失败", variant: "danger" },
};

export function DocumentDetailDialog({
  documentId,
  onClose,
  onDeleted,
}: {
  documentId: string | null;
  onClose: () => void;
  onDeleted?: () => void;
}) {
  const { data: document, isLoading } = useDocumentDetail(documentId);
  const { addVersion, rollback, remove } = useDocumentMutations();
  const [versionFile, setVersionFile] = React.useState<File | null>(null);

  React.useEffect(() => {
    setVersionFile(null);
  }, [documentId]);

  if (!documentId) return null;

  const handleUploadVersion = async () => {
    if (!versionFile) return;
    const form = new FormData();
    form.append("file", versionFile);
    try {
      const result = await addVersion.mutateAsync({ documentId, form });
      toast.success("新版本已入队", {
        description: `任务 ${result.job_id.slice(0, 8)} · 解析成功后才切换生效版本`,
      });
      setVersionFile(null);
    } catch (error) {
      toast.error("上传新版本失败", {
        description: error instanceof Error ? error.message : undefined,
      });
    }
  };

  const handleRollback = async (versionId: string, versionNo: number) => {
    try {
      await rollback.mutateAsync({ documentId, versionId });
      toast.success(`已回滚到 v${versionNo}`);
    } catch (error) {
      toast.error("回滚失败", {
        description: error instanceof Error ? error.message : undefined,
      });
    }
  };

  const handleDelete = async () => {
    try {
      await remove.mutateAsync(documentId);
      toast.success("文档已删除");
      onDeleted?.();
      onClose();
    } catch (error) {
      toast.error("删除失败", {
        description: error instanceof Error ? error.message : undefined,
      });
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl gap-0 p-0">
        <DialogHeader className="border-b border-border px-6 py-4 pr-12">
          <DialogTitle className="flex items-center gap-2">
            <FileText className="size-4 text-danger/80" />
            {document?.title ?? "文档详情"}
          </DialogTitle>
          <DialogDescription>
            {document
              ? `${document.category} · ${(document.species ?? []).join("、") || "通用"} · 共 ${document.page_count ?? 0} 页`
              : "加载中…"}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[52vh] overflow-y-auto px-6 py-5">
          <section>
            <h3 className="eyebrow mb-3">版本历史</h3>
            {isLoading ? (
              <p className="text-[12.5px] text-muted-foreground">加载中…</p>
            ) : (
              <ul className="space-y-2">
                {(document?.versions ?? []).map((version) => {
                  const status = VERSION_STATUS[version.status] ?? {
                    label: version.status,
                    variant: "neutral" as const,
                  };
                  const isCurrent = version.id === document?.current_version_id;
                  return (
                    <li
                      key={version.id}
                      className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface-muted px-3.5 py-3"
                    >
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface text-[12px] font-semibold tabular-nums text-foreground shadow-xs">
                        v{version.version_no}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant={status.variant}>{status.label}</Badge>
                          {isCurrent && <Badge variant="solid">当前版本</Badge>}
                          <span className="text-[11.5px] text-muted-foreground">
                            {version.page_count} 页 · {formatDateTime(version.created_at)}
                          </span>
                        </div>
                        {version.error_message && (
                          <p className="mt-1 flex items-start gap-1.5 text-[11.5px] leading-5 text-danger">
                            <AlertTriangle className="mt-0.5 size-3 shrink-0" />
                            {version.error_message}
                          </p>
                        )}
                        <p className="mt-1 truncate font-mono text-[10.5px] text-subtle-foreground">
                          {version.content_hash}
                        </p>
                      </div>
                      {version.status === "archived" && !isCurrent && (
                        <Button
                          variant="outline"
                          size="xs"
                          onClick={() => handleRollback(version.id, version.version_no)}
                          disabled={rollback.isPending}
                        >
                          <RotateCcw className="size-3" />
                          回滚到此版本
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="mt-6">
            <h3 className="eyebrow mb-3">上传新版本</h3>
            <div className="rounded-xl border border-dashed border-border-strong bg-surface-muted px-4 py-4">
              <Label htmlFor="version-file" className="text-[12.5px] text-muted-foreground">
                选择新的 PDF 文件
              </Label>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Input
                  id="version-file"
                  type="file"
                  accept="application/pdf,.pdf"
                  onChange={(event) => setVersionFile(event.target.files?.[0] ?? null)}
                  className="h-9 max-w-sm file:mr-3 file:rounded-md file:border-0 file:bg-surface-muted file:px-2.5 file:py-1 file:text-[12px] file:text-foreground"
                />
                <Button
                  size="sm"
                  onClick={handleUploadVersion}
                  disabled={!versionFile || addVersion.isPending}
                >
                  <Upload className="size-4" />
                  上传
                </Button>
              </div>
              <p className="mt-2.5 flex items-start gap-1.5 text-[11.5px] leading-5 text-muted-foreground">
                <Clock className="mt-0.5 size-3 shrink-0" />
                新版本只有在解析、切分、向量写入并通过数量校验后才会成为生效版本；旧版本转为归档，可随时回滚。
              </p>
            </div>
          </section>
        </div>

        <div className="flex items-center justify-between border-t border-border px-6 py-3.5">
          <p className="text-[11.5px] text-subtle-foreground">
            删除为软删除，Qdrant 中的向量与原始文件仍会保留。
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={onClose}
            >
              关闭
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDelete}
              disabled={remove.isPending}
              className="border-danger/30 text-danger hover:bg-danger-soft"
            >
              <Trash2 className="size-4" />
              删除文档
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function DocumentDeletedHint() {
  return (
    <span className="inline-flex items-center gap-1 text-[11.5px] text-success">
      <CheckCircle2 className="size-3" />
      已入库
    </span>
  );
}

export function DocumentTitle({ title }: { title: string }) {
  return <span title={truncate(title, 60)}>{title}</span>;
}
