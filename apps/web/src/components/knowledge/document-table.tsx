"use client";

import * as React from "react";
import {
  BookOpen,
  FileText,
  Globe2,
  History,
  MoreHorizontal,
  RotateCcw,
  Trash2,
  Upload,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import type { ManagedDocument } from "@/lib/api/types";
import {
  AUTHORITY_LABELS,
  DOC_STATUS_LABELS,
  DOC_STATUS_TONE,
  MEDIA_TYPE_LABELS,
  REVIEW_STATE_LABELS,
  REVIEW_TONE,
} from "@/lib/labels";
import { cn, formatDateTime, truncate } from "@/lib/utils";

export interface DocumentActions {
  onOpen: (document: ManagedDocument) => void;
  onNewVersion: (document: ManagedDocument) => void;
  onRollback: (document: ManagedDocument) => void;
  onDelete: (document: ManagedDocument) => void;
  onRead: (document: ManagedDocument) => void;
}

function StatusBadges({ document }: { document: ManagedDocument }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
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
    </div>
  );
}

function ReviewBadges({ document }: { document: ManagedDocument }) {
  const technical = document.technical_review_status ?? "pending";
  const domain = document.domain_review_status ?? "pending";
  return (
    <div className="flex flex-col gap-1">
      <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
        <span className="w-8 shrink-0 text-subtle-foreground">技术</span>
        <Badge variant={REVIEW_TONE[technical] ?? "neutral"}>
          {REVIEW_STATE_LABELS[technical] ?? technical}
        </Badge>
      </span>
      <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
        <span className="w-8 shrink-0 text-subtle-foreground">领域</span>
        <Badge variant={REVIEW_TONE[domain] ?? "neutral"}>
          {REVIEW_STATE_LABELS[domain] ?? domain}
        </Badge>
      </span>
    </div>
  );
}

function RowMenu({
  document,
  actions,
}: { document: ManagedDocument; actions: DocumentActions }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`${truncate(document.title, 16)} 的操作`}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>文档操作</DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => actions.onOpen(document)}>
          <History className="size-4 text-muted-foreground" />
          详情 / 版本历史
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => actions.onRead(document)}
          disabled={!document.current_version_id}
        >
          <BookOpen className="size-4 text-muted-foreground" />
          {document.source_type === "html" ? "查看网页来源" : "在阅读器中打开"}
        </DropdownMenuItem>
        {document.source_type !== "html" ? (
          <DropdownMenuItem onSelect={() => actions.onNewVersion(document)}>
            <Upload className="size-4 text-muted-foreground" />
            上传新版本
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuItem
          onSelect={() => actions.onRollback(document)}
          disabled={!document.current_version_id}
        >
          <RotateCcw className="size-4 text-muted-foreground" />
          回滚版本
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => actions.onDelete(document)}
          className="text-danger focus:bg-danger-soft focus:text-danger"
        >
          <Trash2 className="size-4" />
          删除文档
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function DocumentIcon({ document }: { document: ManagedDocument }) {
  return (
    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface shadow-xs">
      {document.source_type === "html" ? (
        <Globe2 className="size-4 text-primary-600" />
      ) : (
        <FileText className="size-4 text-danger/80" />
      )}
    </span>
  );
}

function DocumentTitleLine({ document }: { document: ManagedDocument }) {
  const host = React.useMemo(() => {
    if (!document.source_url) return null;
    try {
      return new URL(document.source_url).host;
    } catch {
      return document.source_url;
    }
  }, [document.source_url]);
  return (
    <span className="min-w-0">
      <span className="block truncate text-[13.5px] font-medium leading-5 text-foreground">
        {document.title}
      </span>
      <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11.5px] text-subtle-foreground">
        <span>{MEDIA_TYPE_LABELS[document.source_type ?? "pdf"] ?? document.source_type}</span>
        {document.source_org ? <span>· {truncate(document.source_org, 18)}</span> : null}
        {host ? <span>· {truncate(host, 24)}</span> : null}
      </span>
    </span>
  );
}

export function DocumentTable({
  documents,
  actions,
  loading,
  filtered,
}: {
  documents: ManagedDocument[];
  actions: DocumentActions;
  loading?: boolean;
  /** Distinguishes "no data at all" from "filters returned nothing". */
  filtered?: boolean;
}) {
  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-[68px] w-full" />
        ))}
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border-strong bg-surface px-6 py-16 text-center">
        <FileText className="size-6 text-subtle-foreground/70" />
        <p className="mt-3 text-[14px] font-medium text-foreground">
          {filtered ? "当前筛选没有匹配的文档" : "知识库还没有文档"}
        </p>
        <p className="mt-1 text-[12.5px] text-muted-foreground">
          {filtered ? "调整筛选条件或搜索词后重试。" : "上传 PDF 或采集资料后即可被检索与引用。"}
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-sm">
      <div className="hidden lg:block">
        <div className="grid grid-cols-[minmax(0,1fr)_176px_112px_136px_104px_44px] items-center gap-3 border-b border-border bg-surface-muted px-4 py-2.5 text-[11px] font-medium uppercase tracking-[0.06em] text-subtle-foreground">
          <span>文档 / 来源</span>
          <span>性质 / 效力</span>
          <span>版本 / 块</span>
          <span>审核状态</span>
          <span>发布</span>
          <span className="text-right">操作</span>
        </div>
        <ul className="divide-y divide-border">
          {documents.map((document) => (
            <li
              key={document.id}
              className="group grid grid-cols-[minmax(0,1fr)_176px_112px_136px_104px_44px] items-center gap-3 px-4 py-3 transition-colors duration-150 hover:bg-surface-muted"
            >
              <button
                type="button"
                onClick={() => actions.onOpen(document)}
                className="flex min-w-0 items-center gap-3 text-left"
              >
                <DocumentIcon document={document} />
                <DocumentTitleLine document={document} />
              </button>

              <div className="min-w-0">
                <p className="truncate text-[12px] font-medium text-foreground">
                  {document.document_type_label}
                </p>
                <p className="mt-0.5 truncate text-[11px] text-subtle-foreground">
                  {AUTHORITY_LABELS[document.authority_level ?? "unknown"] ??
                    document.authority_level}
                </p>
              </div>

              <div className="text-[11.5px] leading-4 text-muted-foreground">
                <p className="tabular-nums">v{document.current_version_no ?? "—"}</p>
                <p className="tabular-nums text-subtle-foreground">
                  {document.parent_chunks}P / {document.child_chunks}C
                </p>
              </div>

              <ReviewBadges document={document} />

              <StatusBadges document={document} />

              <div className="flex justify-end">
                <RowMenu document={document} actions={actions} />
              </div>
            </li>
          ))}
        </ul>
      </div>

      <ul className="divide-y divide-border lg:hidden">
        {documents.map((document) => (
          <li key={document.id} className="px-4 py-3.5">
            <div className="flex items-start gap-3">
              <button
                type="button"
                onClick={() => actions.onOpen(document)}
                className="flex min-w-0 flex-1 items-start gap-3 text-left"
              >
                <DocumentIcon document={document} />
                <DocumentTitleLine document={document} />
              </button>
              <RowMenu document={document} actions={actions} />
            </div>
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
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
              <span className="text-[11px] text-subtle-foreground">
                技术 {REVIEW_STATE_LABELS[document.technical_review_status ?? "pending"]} · 领域{" "}
                {REVIEW_STATE_LABELS[document.domain_review_status ?? "pending"]}
              </span>
            </div>
            <p className="mt-1.5 text-[11px] text-subtle-foreground">
              {formatDateTime(document.created_at)} · v{document.current_version_no ?? "—"} ·{" "}
              {document.page_count ?? "—"} 页 · {document.parent_chunks} 父块 /{" "}
              {document.child_chunks} 子块
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "primary",
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "primary" | "success" | "warning";
}) {
  return (
    <div className="surface-card flex items-center gap-3 px-4 py-3.5">
      <span
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-lg",
          tone === "success"
            ? "bg-success-soft text-success"
            : tone === "warning"
              ? "bg-warning-soft text-warning"
              : "bg-primary-soft text-primary-soft-fg",
        )}
      >
        <Icon className="size-4" />
      </span>
      <div className="min-w-0">
        <p className="text-[11.5px] font-medium text-subtle-foreground">{label}</p>
        <p className="mt-0.5 text-[18px] font-semibold leading-6 tabular-nums text-foreground">
          {value}
        </p>
        {hint && <p className="mt-0.5 truncate text-[11px] text-subtle-foreground">{hint}</p>}
      </div>
    </div>
  );
}
