"use client";

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileText,
  ListTree,
  Loader2,
  RotateCcw,
  ShieldAlert,
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
import { useDocumentMutations } from "@/hooks/use-documents";
import { useManagedDocument } from "@/hooks/use-management";
import {
  AUTHORITY_LABELS,
  DOC_STATUS_LABELS,
  DOC_STATUS_TONE,
  MEDIA_TYPE_LABELS,
  REVIEW_STATE_LABELS,
  REVIEW_TONE,
} from "@/lib/labels";
import { cn, formatDateTime, truncate } from "@/lib/utils";

const VERSION_STATUS: Record<
  string,
  { label: string; variant: "success" | "warning" | "danger" | "neutral" }
> = {
  ready: { label: "解析完成", variant: "success" },
  archived: { label: "已归档", variant: "neutral" },
  processing: { label: "解析中", variant: "warning" },
  failed: { label: "失败", variant: "danger" },
};

const JOB_STATUS: Record<
  string,
  { label: string; variant: "success" | "warning" | "danger" | "neutral" }
> = {
  succeeded: { label: "成功", variant: "success" },
  running: { label: "进行中", variant: "warning" },
  queued: { label: "排队中", variant: "neutral" },
  failed: { label: "失败", variant: "danger" },
  cancelled: { label: "已取消", variant: "neutral" },
};

const TABS = [
  { id: "overview", label: "概览与可信度" },
  { id: "versions", label: "版本历史" },
  { id: "chunks", label: "解析块" },
  { id: "jobs", label: "处理任务" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-subtle-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 break-words text-[12px] leading-5 text-foreground">{children}</dd>
    </div>
  );
}

function readString(source: Record<string, unknown>, key: string): string | null {
  const value = source[key];
  return typeof value === "string" && value.trim() ? value : null;
}

export function DocumentDetailDialog({
  documentId,
  onClose,
  onDeleted,
  onRead,
}: {
  documentId: string | null;
  onClose: () => void;
  onDeleted?: () => void;
  onRead?: (documentId: string, versionId: string, mediaType: string) => void;
}) {
  const { data: document, isLoading, isError, error } = useManagedDocument(documentId);
  const { addVersion, rollback, remove } = useDocumentMutations();
  const [versionFile, setVersionFile] = React.useState<File | null>(null);
  const [tab, setTab] = React.useState<TabId>("overview");

  React.useEffect(() => {
    setVersionFile(null);
    setTab("overview");
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
    } catch (uploadError) {
      toast.error("上传新版本失败", {
        description: uploadError instanceof Error ? uploadError.message : undefined,
      });
    }
  };

  const handleRollback = async (versionId: string, versionNo: number) => {
    try {
      await rollback.mutateAsync({ documentId, versionId });
      toast.success(`已回滚到 v${versionNo}`);
    } catch (rollbackError) {
      toast.error("回滚失败", {
        description: rollbackError instanceof Error ? rollbackError.message : undefined,
      });
    }
  };

  const handleDelete = async () => {
    try {
      await remove.mutateAsync(documentId);
      toast.success("文档已删除");
      onDeleted?.();
      onClose();
    } catch (deleteError) {
      toast.error("删除失败", {
        description: deleteError instanceof Error ? deleteError.message : undefined,
      });
    }
  };

  const source = (document?.source ?? {}) as Record<string, unknown>;
  const storage = (document?.storage ?? {}) as Record<string, unknown>;
  const review = (document?.review ?? {}) as Record<string, unknown>;
  const mediaType = document?.source_type ?? "pdf";
  const sourceUrl =
    readString(source, "source_url") ?? readString(source, "final_url") ?? null;
  const flags = document?.review_flag_details ?? [];
  const publishBlockers: string[] = [];
  if (document && document.status !== "active") publishBlockers.push("状态不是 active");
  if (document && document.verification_status !== "verified") publishBlockers.push("文档未核验");
  if (document && !document.current_version_id) publishBlockers.push("没有当前版本");
  if (document && document.child_chunks === 0) publishBlockers.push("没有已索引子块");

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl gap-0 p-0">
        <DialogHeader className="border-b border-border px-6 py-4 pr-12">
          <DialogTitle className="flex items-center gap-2">
            <FileText className={cn("size-4", mediaType === "html" ? "text-primary-600" : "text-danger/80")} />
            {document?.title ?? "文档详情"}
          </DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-2">
            {document ? (
              <>
                <Badge variant="outline">{MEDIA_TYPE_LABELS[mediaType] ?? mediaType}</Badge>
                <Badge variant="outline">{document.document_type_label}</Badge>
                <Badge variant={DOC_STATUS_TONE[document.status] ?? "neutral"}>
                  {DOC_STATUS_LABELS[document.status] ?? document.status}
                </Badge>
                {document.retrievable ? (
                  <Badge variant="success">在线检索</Badge>
                ) : document.published ? (
                  <Badge variant="warning">已发布 · 索引未就绪</Badge>
                ) : (
                  <Badge variant="warning">不进入检索</Badge>
                )}
                <span>
                  {document.category} · {(document.species ?? []).join("、") || "通用"} ·{" "}
                  {document.page_count ?? 0} 页
                </span>
              </>
            ) : (
              "加载中…"
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="flex shrink-0 gap-1 border-b border-border px-6 pt-2">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={cn(
                "border-b-2 px-3 py-2 text-[12px] transition-colors",
                tab === item.id
                  ? "border-primary font-medium text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="max-h-[58vh] overflow-y-auto px-6 py-5">
          {isLoading ? (
            <div className="flex items-center gap-2 py-8 text-[12.5px] text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> 加载文档详情…
            </div>
          ) : isError ? (
            <div className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-[12.5px] text-danger">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              {error instanceof Error ? error.message : "文档详情加载失败"}
            </div>
          ) : document ? (
            <>
              {tab === "overview" && (
                <div className="space-y-6">
                  <section>
                    <h3 className="eyebrow mb-3">来源与存储</h3>
                    <dl className="grid gap-x-6 gap-y-3.5 sm:grid-cols-2">
                      <Field label="发布机构">{document.source_org ?? "未标注"}</Field>
                      <Field label="原始链接">
                        {sourceUrl ? (
                          <a
                            href={sourceUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-primary-600 hover:underline"
                          >
                            {truncate(sourceUrl, 48)}
                            <ExternalLink className="size-3" />
                          </a>
                        ) : (
                          "未登记"
                        )}
                      </Field>
                      <Field label="语言 / 地区">
                        {readString(source, "language") ?? "未标注"} ·{" "}
                        {readString(source, "region") ?? "未标注"}
                      </Field>
                      <Field label="许可证">
                        {readString(source, "license") ?? "未登记"}
                      </Field>
                      <Field label="效力等级">
                        {AUTHORITY_LABELS[document.authority_level ?? "unknown"] ??
                          document.authority_level}
                      </Field>
                      <Field label="发布 / 生效年份">
                        {document.publish_year ?? "—"} /{" "}
                        {document.effective_date ? document.effective_date.slice(0, 10) : "—"}
                      </Field>
                      <Field label="存储策略">{document.storage_policy_label}</Field>
                      <Field label="来源标识">
                        <span className="font-mono text-[11px]">
                          {readString(source, "source_id") ?? "—"}
                        </span>
                      </Field>
                    </dl>
                  </section>

                  <section>
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <h3 className="eyebrow">发布与审核</h3>
                      <span className="text-[11px] text-subtle-foreground">
                        程序检查 ≠ 专家认可
                      </span>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <div className="rounded-xl border border-border bg-surface-muted px-3.5 py-3">
                        <p className="text-[11px] text-subtle-foreground">技术检查（解析/来源）</p>
                        <Badge
                          variant={
                            REVIEW_TONE[document.technical_review_status ?? "pending"] ?? "neutral"
                          }
                          className="mt-1.5"
                        >
                          {REVIEW_STATE_LABELS[document.technical_review_status ?? "pending"] ??
                            document.technical_review_status}
                        </Badge>
                      </div>
                      <div className="rounded-xl border border-border bg-surface-muted px-3.5 py-3">
                        <p className="text-[11px] text-subtle-foreground">领域审核（水产专家）</p>
                        <Badge
                          variant={
                            REVIEW_TONE[document.domain_review_status ?? "pending"] ?? "neutral"
                          }
                          className="mt-1.5"
                        >
                          {REVIEW_STATE_LABELS[document.domain_review_status ?? "pending"] ??
                            document.domain_review_status}
                        </Badge>
                      </div>
                    </div>
                    <p className="mt-2 text-[11.5px] leading-5 text-muted-foreground">
                      {String(review.domain_note ?? "")}
                    </p>
                    {publishBlockers.length > 0 ? (
                      <div className="mt-3 flex items-start gap-2 rounded-xl border border-warning/30 bg-warning-soft px-3.5 py-2.5 text-[11.5px] leading-5 text-warning">
                        <ShieldAlert className="mt-0.5 size-3.5 shrink-0" />
                        <span>
                          尚未满足全部上线条件：{publishBlockers.join("、")}。发布仍需在后端确认当前版本已索引。
                        </span>
                      </div>
                    ) : (
                      <p className="mt-3 flex items-center gap-1.5 text-[11.5px] text-success">
                        <CheckCircle2 className="size-3.5" />
                        已满足上线条件；实际发布由后端 promote 接口再次校验。
                      </p>
                    )}
                  </section>

                  <section>
                    <h3 className="eyebrow mb-2">解析异常 / 风险标记</h3>
                    {flags.length === 0 ? (
                      <p className="text-[12px] text-muted-foreground">未记录风险标记。</p>
                    ) : (
                      <ul className="space-y-1.5">
                        {flags.map((flag) => (
                          <li
                            key={flag.code}
                            className="flex items-start gap-2 rounded-lg border border-warning/25 bg-warning-soft/60 px-3 py-2 text-[11.5px] leading-5 text-warning"
                          >
                            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                            <span>
                              {flag.label}
                              {flag.label !== flag.code ? (
                                <code className="ml-1 text-[10px] opacity-70">
                                  （{flag.code}）
                                </code>
                              ) : null}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <div className="flex flex-wrap gap-2">
                    {document.current_version_id ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          onRead?.(document.id, document.current_version_id as string, mediaType)
                        }
                      >
                        <ExternalLink className="size-3.5" />
                        {mediaType === "html" ? "打开原文快照" : "在阅读器中定位"}
                      </Button>
                    ) : null}
                  </div>
                </div>
              )}

              {tab === "versions" && (
                <section>
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="eyebrow">版本历史</h3>
                    <span className="text-[11px] text-subtle-foreground">
                      共 {document.versions.length} 个版本
                    </span>
                  </div>
                  <ul className="space-y-2">
                    {document.versions.map((version) => {
                      const status = VERSION_STATUS[version.status] ?? {
                        label: version.status,
                        variant: "neutral" as const,
                      };
                      const isCurrent = version.id === document.current_version_id;
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
                                {version.page_count} 页 · {version.parent_chunks}P/
                                {version.child_chunks}C
                              </span>
                            </div>
                            <p className="mt-1 text-[11px] text-subtle-foreground">
                              {formatDateTime(version.activated_at ?? version.created_at)} ·{" "}
                              {version.parser_name ?? "parser"}{" "}
                              {version.parser_version ?? ""}
                            </p>
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

                  {mediaType !== "html" ? (
                    <div className="mt-5 rounded-xl border border-dashed border-border-strong bg-surface-muted px-4 py-4">
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
                  ) : (
                    <p className="mt-4 text-[11.5px] text-muted-foreground">
                      网页来源按快照版本留存，不提供 PDF 新版本上传入口。
                    </p>
                  )}
                </section>
              )}

              {tab === "chunks" && (
                <section>
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="eyebrow">当前版本解析块（预览）</h3>
                    <span className="text-[11px] text-subtle-foreground">
                      {document.parent_chunks} 父块 / {document.child_chunks} 子块
                    </span>
                  </div>
                  {document.chunks_preview.length === 0 ? (
                    <p className="text-[12px] text-muted-foreground">当前版本没有可预览的解析块。</p>
                  ) : (
                    <ul className="space-y-2">
                      {document.chunks_preview.map((chunk) => (
                        <li
                          key={chunk.id}
                          className="rounded-xl border border-border bg-surface-muted px-3.5 py-3"
                        >
                          <div className="mb-1.5 flex flex-wrap items-center gap-2">
                            <Badge variant={chunk.chunk_role === "parent" ? "default" : "outline"}>
                              {chunk.chunk_role === "parent" ? "父块" : "子块"} #{chunk.ordinal}
                            </Badge>
                            <span className="text-[11px] text-subtle-foreground">
                              p.{chunk.page_from}
                              {chunk.page_to !== chunk.page_from ? `–${chunk.page_to}` : ""}
                            </span>
                            {chunk.heading_path.length > 0 ? (
                              <span className="truncate text-[11px] text-muted-foreground">
                                {chunk.heading_path.join(" › ")}
                              </span>
                            ) : null}
                          </div>
                          <p className="whitespace-pre-wrap text-[12px] leading-5 text-foreground">
                            {chunk.content}
                            {chunk.truncated ? "…" : ""}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )}

              {tab === "jobs" && (
                <section>
                  <h3 className="eyebrow mb-3">处理任务</h3>
                  {document.jobs.length === 0 ? (
                    <p className="text-[12px] text-muted-foreground">没有任务记录。</p>
                  ) : (
                    <ul className="space-y-2">
                      {document.jobs.map((job) => {
                        const status = JOB_STATUS[job.status] ?? {
                          label: job.status,
                          variant: "neutral" as const,
                        };
                        return (
                          <li
                            key={job.id}
                            className="rounded-xl border border-border bg-surface-muted px-3.5 py-3"
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge variant={status.variant}>{status.label}</Badge>
                              <span className="text-[11.5px] text-muted-foreground">
                                v{job.version_no} · {job.job_type} · {job.progress}% · 尝试{" "}
                                {job.attempts}
                              </span>
                              <span className="text-[11px] text-subtle-foreground">
                                {formatDateTime(job.started_at ?? job.created_at)}
                              </span>
                            </div>
                            {job.error_message ? (
                              <p className="mt-1.5 flex items-start gap-1.5 text-[11.5px] leading-5 text-danger">
                                <AlertTriangle className="mt-0.5 size-3 shrink-0" />
                                {job.error_code ? `${job.error_code}: ` : ""}
                                {job.error_message}
                              </p>
                            ) : null}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </section>
              )}
            </>
          ) : null}
        </div>

        <div className="flex items-center justify-between border-t border-border px-6 py-3.5">
          <p className="max-w-[60%] text-[11.5px] leading-4 text-subtle-foreground">
            删除为软删除，原文与向量保留；不会从其他会话的历史引用中伪造可访问性。
          </p>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
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
