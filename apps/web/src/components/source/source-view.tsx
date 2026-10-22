"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  FileText,
  Globe2,
  HelpCircle,
  Loader2,
  ShieldAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useDocumentChunks, useFaqDetail, useManagedDocument } from "@/hooks/use-management";
import {
  AUTHORITY_LABELS,
  DOC_STATUS_LABELS,
  DOC_STATUS_TONE,
  MEDIA_TYPE_LABELS,
  REVIEW_STATE_LABELS,
  REVIEW_TONE,
  unavailableReasonLabel,
} from "@/lib/labels";
import { formatDateTime } from "@/lib/utils";

function Shell({
  title,
  subtitle,
  children,
  backHref = "/knowledge",
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  backHref?: string;
}) {
  return (
    <div className="scroll-contain h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[900px] px-4 py-6 sm:px-6 sm:py-8">
        <Link
          href={backHref}
          className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          返回
        </Link>
        <header className="mt-4 border-b border-border pb-4">
          <h1 className="text-[20px] font-semibold leading-8 text-foreground">{title}</h1>
          {subtitle ? <div className="mt-2 text-[12px] text-muted-foreground">{subtitle}</div> : null}
        </header>
        <main className="py-5">{children}</main>
      </div>
    </div>
  );
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function SourceView() {
  const params = useSearchParams();
  const faqId = params.get("faq_id");
  const documentId = params.get("document_id");
  if (faqId) {
    return UUID_PATTERN.test(faqId) ? (
      <FaqSource faqId={faqId} />
    ) : (
      <Shell title="FAQ 链接无效">
        <p className="text-[13px] text-muted-foreground">faq_id 不是合法的条目 ID。</p>
      </Shell>
    );
  }
  if (documentId) {
    return UUID_PATTERN.test(documentId) ? (
      <DocumentSource
        documentId={documentId}
        versionId={
          params.get("version_id") && UUID_PATTERN.test(params.get("version_id") as string)
            ? params.get("version_id")
            : null
        }
        page={params.get("page") ? Number(params.get("page")) : null}
      />
    ) : (
      <Shell title="来源链接无效">
        <p className="text-[13px] text-muted-foreground">document_id 不是合法的文档 ID。</p>
      </Shell>
    );
  }
  return (
    <Shell title="来源不可用">
      <p className="text-[13px] text-muted-foreground">链接缺少 document_id 或 faq_id 参数。</p>
    </Shell>
  );
}

function FaqSource({ faqId }: { faqId: string }) {
  const { data: faq, isLoading, isError, error } = useFaqDetail(faqId);

  if (isLoading) {
    return (
      <Shell title="正在加载 FAQ…">
        <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> 读取 FAQ 与支撑证据…
        </div>
      </Shell>
    );
  }
  if (isError || !faq) {
    return (
      <Shell title="FAQ 不存在或不可访问">
        <div className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 text-[12.5px] text-warning">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" />
          {error instanceof Error ? error.message : "没有找到该 FAQ 条目。"}
        </div>
      </Shell>
    );
  }

  const seeded = faq.review_provenance === "program_seeded";
  return (
    <Shell
      title={faq.question}
      subtitle={
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">
            <HelpCircle className="mr-1 size-3" />
            已核验 FAQ
          </Badge>
          <Badge variant={REVIEW_TONE[faq.review_status] ?? "neutral"}>
            {REVIEW_STATE_LABELS[faq.review_status] ?? faq.review_status}
          </Badge>
          <Badge variant={faq.indexed ? "success" : "warning"}>
            {faq.indexed ? "已写入 FAQ 索引" : "未写入索引"}
          </Badge>
          <span>{(faq.species ?? []).join("、") || "通用"}</span>
          {faq.topic ? <span>· {faq.topic}</span> : null}
        </div>
      }
    >
      <div className="space-y-5">
        <section className="rounded-2xl border border-border bg-surface p-4">
          <h2 className="eyebrow mb-2">答案</h2>
          <p className="whitespace-pre-wrap text-[13.5px] leading-7 text-foreground">{faq.answer}</p>
        </section>

        <section
          className={
            seeded
              ? "rounded-2xl border border-warning/30 bg-warning-soft px-4 py-3.5"
              : "rounded-2xl border border-border bg-surface-muted px-4 py-3.5"
          }
        >
          <h2 className="eyebrow mb-2 flex items-center gap-1.5">
            {seeded ? (
              <AlertTriangle className="size-3.5 text-warning" />
            ) : (
              <CheckCircle2 className="size-3.5 text-success" />
            )}
            审核来源
          </h2>
          <p className="text-[12.5px] leading-6 text-foreground">{faq.review_provenance_label}</p>
          <dl className="mt-2 grid gap-x-6 gap-y-1.5 text-[11.5px] text-muted-foreground sm:grid-cols-2">
            <div>
              复核人：<span className="text-foreground">{faq.reviewer ?? "未记录"}</span>
            </div>
            <div>
              复核时间：
              <span className="text-foreground">{formatDateTime(faq.reviewed_at)}</span>
            </div>
            <div>
              领域审核：
              <span className="text-foreground">
                {faq.domain_review_status === "not_recorded"
                  ? "未记录（不等同于专家确认）"
                  : REVIEW_STATE_LABELS[faq.domain_review_status] ?? faq.domain_review_status}
              </span>
            </div>
            <div>
              来源数据集：
              <span className="text-foreground">{faq.source_dataset}</span>
            </div>
          </dl>
          {seeded ? (
            <p className="mt-2 text-[11.5px] leading-5 text-warning">
              该条目由程序从已发布原文种子化生成，只代表可追溯，不代表水产领域专家逐条确认。
            </p>
          ) : null}
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="eyebrow">支撑原文（{faq.supporting.length}）</h2>
            <span className="text-[11px] text-subtle-foreground">FAQ 本身不是 PDF</span>
          </div>
          {faq.supporting.length === 0 ? (
            <p className="text-[12.5px] text-muted-foreground">没有登记支撑原文。</p>
          ) : (
            <ul className="space-y-2.5">
              {faq.supporting.map((support, index) => (
                <li key={`${support.document_id}-${index}`} className="rounded-xl border border-border bg-surface p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium text-foreground">
                        {support.title ?? "支撑文献已不存在"}
                      </p>
                      <p className="mt-0.5 text-[11px] text-subtle-foreground">
                        {support.source_type ? MEDIA_TYPE_LABELS[support.source_type] ?? support.source_type : "原文"}
                        {support.version_no ? ` · v${support.version_no}` : ""}
                        {support.page && support.source_type !== "html"
                          ? ` · 第 ${support.page} 页`
                          : ""}
                      </p>
                    </div>
                    {support.available ? (
                      support.document_id && support.version_id ? (
                        <Button variant="outline" size="xs" asChild>
                          <Link
                            href={
                              support.source_type === "html"
                                ? `/source?document_id=${support.document_id}&version_id=${support.version_id}${support.page ? `&page=${support.page}` : ""}`
                                : `/reader?document_id=${support.document_id}&version_id=${support.version_id}${support.page ? `&page=${support.page}` : ""}`
                            }
                          >
                            打开原文
                            <ArrowUpRight className="size-3" />
                          </Link>
                        </Button>
                      ) : null
                    ) : (
                      <Badge variant="warning">{unavailableReasonLabel(support.unavailable_reason)}</Badge>
                    )}
                  </div>
                  {support.quote ? (
                    <blockquote className="mt-2 border-l-2 border-primary-300 pl-3 text-[12.5px] leading-6 text-muted-foreground">
                      {support.quote}
                    </blockquote>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        {faq.original_source_url ? (
          <a
            href={faq.original_source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[12px] text-primary-600 hover:underline"
          >
            原始来源链接
            <ArrowUpRight className="size-3" />
          </a>
        ) : null}
      </div>
    </Shell>
  );
}

function DocumentSource({
  documentId,
  versionId,
  page,
}: {
  documentId: string;
  versionId: string | null;
  page: number | null;
}) {
  const { data: document, isLoading, isError, error } = useManagedDocument(documentId);
  const { data: chunks, isLoading: chunksLoading } = useDocumentChunks(documentId, {
    version_id: versionId ?? undefined,
    // Parent blocks keep the reading context; child blocks would duplicate
    // the same text in this snapshot view.
    role: "parent",
    page: page ?? undefined,
    limit: 50,
  });

  if (isLoading) {
    return (
      <Shell title="正在加载来源…">
        <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> 读取文档与快照…
        </div>
      </Shell>
    );
  }
  if (isError || !document) {
    return (
      <Shell title="来源文档不可访问">
        <div className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 text-[12.5px] text-warning">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" />
          {error instanceof Error ? error.message : "文档不存在或已删除。"}
        </div>
      </Shell>
    );
  }

  const isHtml = document.source_type === "html";
  const shownVersion = document.versions?.find(
    (version) => version.id === (versionId ?? document.current_version_id),
  );
  return (
    <Shell
      title={document.title}
      subtitle={
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">
            {isHtml ? <Globe2 className="mr-1 size-3" /> : <FileText className="mr-1 size-3" />}
            {MEDIA_TYPE_LABELS[document.source_type ?? "pdf"]}
          </Badge>
          <Badge variant={DOC_STATUS_TONE[document.status] ?? "neutral"}>
            {DOC_STATUS_LABELS[document.status] ?? document.status}
          </Badge>
          <Badge variant="outline">{document.document_type_label}</Badge>
          <span>{AUTHORITY_LABELS[document.authority_level ?? "unknown"] ?? document.authority_level}</span>
          <span>· {document.source_org ?? "机构未标注"}</span>
        </div>
      }
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-2">
          {document.source_url ? (
            <Button variant="outline" size="sm" asChild>
              <a href={document.source_url} target="_blank" rel="noreferrer">
                原始网页
                <ArrowUpRight className="size-3.5" />
              </a>
            </Button>
          ) : null}
          {!isHtml && document.current_version_id ? (
            <Button variant="outline" size="sm" asChild>
              <Link
                href={`/reader?document_id=${document.id}&version_id=${
                  versionId ?? document.current_version_id
                }${page ? `&page=${page}` : ""}`}
              >
                <BookOpen className="size-3.5" />
                在 PDF 阅读器中打开
              </Link>
            </Button>
          ) : null}
        </div>

        {isHtml ? (
          <div className="rounded-xl border border-border bg-surface-muted px-4 py-3 text-[11.5px] leading-5 text-muted-foreground">
            这里展示的是入库时保存的网页解析快照（v{shownVersion?.version_no ?? "—"}），不是实时网页。引用定位使用段落/块锚点；快照与原网页当前内容可能不同。
          </div>
        ) : null}

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="eyebrow">
              原文快照{!isHtml && page ? ` · 第 ${page} 页附近` : ""}
            </h2>
            <span className="text-[11px] text-subtle-foreground">
              {chunks?.total ?? 0} 个块
            </span>
          </div>
          {chunksLoading ? (
            <p className="text-[12.5px] text-muted-foreground">加载解析块…</p>
          ) : (chunks?.items.length ?? 0) === 0 ? (
            <p className="text-[12.5px] text-muted-foreground">该版本没有可展示的解析块。</p>
          ) : (
            <ul className="space-y-2">
              {chunks?.items.map((chunk) => (
                <li key={chunk.id} className="rounded-xl border border-border bg-surface px-4 py-3">
                  <div className="mb-1.5 flex flex-wrap items-center gap-2">
                    <Badge variant={chunk.chunk_role === "parent" ? "default" : "outline"}>
                      {chunk.chunk_role === "parent" ? "父块" : "子块"} #{chunk.ordinal}
                    </Badge>
                    <span className="text-[11px] text-subtle-foreground">
                      {isHtml
                        ? "网页段落"
                        : `p.${chunk.page_from}${
                            chunk.page_to !== chunk.page_from ? `–${chunk.page_to}` : ""
                          }`}
                    </span>
                    {chunk.heading_path.length > 0 ? (
                      <span className="truncate text-[11px] text-muted-foreground">
                        {chunk.heading_path.join(" › ")}
                      </span>
                    ) : null}
                  </div>
                  <p className="whitespace-pre-wrap text-[12.5px] leading-6 text-foreground">
                    {chunk.content}
                    {chunk.truncated ? "…" : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Shell>
  );
}
