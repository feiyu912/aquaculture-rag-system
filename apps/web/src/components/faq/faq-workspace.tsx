"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowUpRight,
  BookOpenCheck,
  ChevronLeft,
  ChevronRight,
  Database,
  HelpCircle,
  Info,
  Loader2,
  Search,
  ShieldCheck,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useCapabilities, useFaqPage, useFaqStats } from "@/hooks/use-management";
import { REVIEW_STATE_LABELS, REVIEW_TONE } from "@/lib/labels";
import { cn, formatDateTime, truncate } from "@/lib/utils";

function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

const REVIEW_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "verified", label: "已核验" },
  { value: "pending", label: "待核验" },
  { value: "rejected", label: "已拒绝" },
];

const EVIDENCE_OPTIONS = [
  { value: "", label: "全部证据链" },
  { value: "supported", label: "有支撑原文" },
  { value: "insufficient", label: "证据不足" },
  { value: "invalid", label: "证据失效" },
];

const INDEX_OPTIONS = [
  { value: "", label: "索引状态不限" },
  { value: "true", label: "已写入索引" },
  { value: "false", label: "未写入索引" },
];

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
      <span className="sr-only">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 rounded-md border border-border bg-surface px-2 text-[12px] text-foreground"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function FaqWorkspace() {
  const [query, setQuery] = React.useState("");
  const [reviewStatus, setReviewStatus] = React.useState("");
  const [evidenceStatus, setEvidenceStatus] = React.useState("");
  const [indexed, setIndexed] = React.useState("");
  const [page, setPage] = React.useState(1);
  const pageSize = 20;
  const debouncedQuery = useDebounced(query.trim());

  const { data: stats, isLoading: statsLoading } = useFaqStats();
  const { data: capabilities } = useCapabilities();
  const { data, isLoading, isError, error, isFetching } = useFaqPage({
    q: debouncedQuery || undefined,
    review_status: reviewStatus || undefined,
    evidence_status: evidenceStatus || undefined,
    indexed: (indexed as "true" | "false" | undefined) || undefined,
    limit: pageSize,
    offset: (page - 1) * pageSize,
  });

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="scroll-contain h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[1180px] px-4 py-6 sm:px-6 sm:py-8">
        <header>
          <h1 className="text-[20px] font-semibold text-foreground">FAQ 审核与证据链</h1>
          <p className="mt-1 max-w-3xl text-[12.5px] leading-5 text-muted-foreground">
            FAQ 只在原文证据不足时补充，不会替代原始文献。检索是否启用由服务端能力开关决定，前端按钮不能绕过。
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge variant={capabilities?.faq_retrieval ? "success" : "neutral"}>
              FAQ 检索 {capabilities?.faq_retrieval ? "已启用" : "未启用"}
            </Badge>
            <Badge variant={capabilities?.faq_direct_answer ? "success" : "neutral"}>
              FAQ 直答 {capabilities?.faq_direct_answer ? "已启用" : "未启用"}
            </Badge>
            <Badge variant="outline">默认模式 document_rag</Badge>
          </div>
        </header>

        <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
          <div className="rounded-xl border border-border bg-surface px-4 py-3">
            <p className="text-[11px] text-subtle-foreground">FAQ 总数</p>
            <p className="mt-1 text-[20px] font-semibold tabular-nums text-foreground">
              {statsLoading ? "—" : stats?.total ?? 0}
            </p>
          </div>
          <div className="rounded-xl border border-border bg-surface px-4 py-3">
            <p className="text-[11px] text-subtle-foreground">已核验（数据库）</p>
            <p className="mt-1 text-[20px] font-semibold tabular-nums text-success">
              {statsLoading ? "—" : stats?.verified ?? 0}
            </p>
          </div>
          <div className="rounded-xl border border-border bg-surface px-4 py-3">
            <p className="text-[11px] text-subtle-foreground">实际写入索引</p>
            <p className="mt-1 text-[20px] font-semibold tabular-nums text-foreground">
              {statsLoading ? "—" : stats?.verified_indexed ?? 0}
            </p>
            <p className="mt-0.5 text-[10.5px] text-subtle-foreground">
              Qdrant 点 {stats?.index_points ?? "不可用"}
            </p>
          </div>
          <div className="rounded-xl border border-border bg-surface px-4 py-3">
            <p className="text-[11px] text-subtle-foreground">待核验</p>
            <p className="mt-1 text-[20px] font-semibold tabular-nums text-warning">
              {statsLoading ? "—" : stats?.pending ?? 0}
            </p>
          </div>
          <div className="rounded-xl border border-border bg-surface px-4 py-3">
            <p className="text-[11px] text-subtle-foreground">已拒绝</p>
            <p className="mt-1 text-[20px] font-semibold tabular-nums text-muted-foreground">
              {statsLoading ? "—" : stats?.rejected ?? 0}
            </p>
          </div>
        </div>

        <div className="mt-3 flex items-start gap-2 rounded-xl border border-info/25 bg-info-soft px-3.5 py-2.5 text-[11.5px] leading-5 text-info">
          <Info className="mt-0.5 size-3.5 shrink-0" />
          “已核验（数据库）”不等于“已写入索引”，也不等于“被回答实际引用”，更不等于答案正确或“领域专家确认”。程序种子条目会明确标注复制来源，不会显示成专家审核。
        </div>

        <section className="mt-6">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px] flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
              <Input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                placeholder="搜索问题或答案"
                aria-label="搜索 FAQ"
                className="h-8 pl-8 text-[12.5px]"
              />
            </div>
            <Select
              label="审核状态"
              value={reviewStatus}
              options={REVIEW_OPTIONS}
              onChange={(value) => {
                setReviewStatus(value);
                setPage(1);
              }}
            />
            <Select
              label="证据链状态"
              value={evidenceStatus}
              options={EVIDENCE_OPTIONS}
              onChange={(value) => {
                setEvidenceStatus(value);
                setPage(1);
              }}
            />
            <Select
              label="索引状态"
              value={indexed}
              options={INDEX_OPTIONS}
              onChange={(value) => {
                setIndexed(value);
                setPage(1);
              }}
            />
          </div>

          <div className="mt-2 flex items-center justify-between text-[11px] text-subtle-foreground">
            <span>
              共 {total} 条，第 {total === 0 ? 0 : (page - 1) * pageSize + 1}–
              {Math.min(page * pageSize, total)} 条
            </span>
            {isFetching ? (
              <span className="inline-flex items-center gap-1">
                <Loader2 className="size-3 animate-spin" /> 更新中
              </span>
            ) : null}
          </div>

          <div className="mt-2 space-y-2.5">
            {isLoading ? (
              Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-28 w-full" />)
            ) : isError ? (
              <div className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-[12.5px] text-danger">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                {error instanceof Error ? error.message : "FAQ 列表加载失败"}
              </div>
            ) : (data?.items.length ?? 0) === 0 ? (
              <div className="rounded-2xl border border-dashed border-border-strong bg-surface px-6 py-14 text-center">
                <HelpCircle className="mx-auto size-6 text-subtle-foreground/70" />
                <p className="mt-3 text-[13.5px] font-medium text-foreground">没有匹配的 FAQ</p>
                <p className="mt-1 text-[12px] text-muted-foreground">调整审核/索引筛选后重试。</p>
              </div>
            ) : (
              data?.items.map((faq) => {
                const seeded = faq.review_provenance === "program_seeded";
                return (
                  <Link
                    key={faq.id}
                    href={`/source?faq_id=${faq.id}`}
                    className="block rounded-2xl border border-border bg-surface px-4 py-3.5 transition-colors hover:border-border-strong hover:bg-surface-muted/40"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-[13.5px] font-medium leading-5 text-foreground">
                          {faq.question}
                        </p>
                        <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-muted-foreground">
                          {faq.answer}
                        </p>
                      </div>
                      <ArrowUpRight className="size-4 shrink-0 text-subtle-foreground" />
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Badge variant={REVIEW_TONE[faq.review_status] ?? "neutral"}>
                        {faq.review_status === "pending"
                          ? "待核验"
                          : REVIEW_STATE_LABELS[faq.review_status] ?? faq.review_status}
                      </Badge>
                      <Badge variant={faq.indexed ? "success" : "warning"}>
                        {faq.indexed ? "已写入索引" : "未写入索引"}
                      </Badge>
                      <Badge variant={seeded ? "warning" : "outline"}>
                        {seeded
                          ? "程序种子 · 非专家逐条审核"
                          : faq.review_provenance === "human_recorded"
                            ? "人工记录（非专家确认）"
                            : "核验来源未记录"}
                      </Badge>
                      <Badge variant="neutral">支撑 {faq.supporting_count}</Badge>
                      {faq.species.length > 0 ? (
                        <Badge variant="neutral">{truncate(faq.species.join("、"), 16)}</Badge>
                      ) : null}
                      <span className="text-[11px] text-subtle-foreground">
                        {faq.reviewer ?? "复核人未记录"} · {formatDateTime(faq.reviewed_at)}
                      </span>
                    </div>
                    {seeded ? (
                      <p className="mt-1.5 flex items-start gap-1 text-[11px] leading-4 text-warning">
                        <AlertTriangle className="mt-0.5 size-3 shrink-0" />
                        {faq.review_provenance_label}；领域审核：
                        {faq.domain_review_status === "not_recorded"
                          ? "未记录（不等同专家确认）"
                          : faq.domain_review_status}
                      </p>
                    ) : null}
                  </Link>
                );
              })
            )}
          </div>

          {total > 0 ? (
            <div className="mt-4 flex items-center justify-between">
              <span className="text-[11px] text-subtle-foreground">
                第 {page} / {pages} 页
              </span>
              <div className="flex items-center gap-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1 || isFetching}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  <ChevronLeft className="size-3.5" />
                  上一页
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= pages || isFetching}
                  onClick={() => setPage((value) => value + 1)}
                >
                  下一页
                  <ChevronRight className="size-3.5" />
                </Button>
              </div>
            </div>
          ) : null}
        </section>

        <section className="mt-8 grid gap-3 sm:grid-cols-3">
          <div className="surface-card px-4 py-3">
            <p className="flex items-center gap-1.5 text-[12px] font-medium text-foreground">
              <ShieldCheck className="size-3.5 text-success" /> 核验前置
            </p>
            <p className="mt-1 text-[11.5px] leading-5 text-muted-foreground">
              必须有仍处于 active、且为当前版本、已发布的支撑文献；否则不能核验。
            </p>
          </div>
          <div className="surface-card px-4 py-3">
            <p className="flex items-center gap-1.5 text-[12px] font-medium text-foreground">
              <BookOpenCheck className="size-3.5 text-primary-600" /> 引用不等于正确
            </p>
            <p className="mt-1 text-[11.5px] leading-5 text-muted-foreground">
              被检索候选接受、最终被模型引用、答案事实正确，是三件不同的事，界面分开标记。
            </p>
          </div>
          <div className="surface-card px-4 py-3">
            <p className="flex items-center gap-1.5 text-[12px] font-medium text-foreground">
              <Database className="size-3.5 text-primary-600" /> 实际索引
            </p>
            <p className="mt-1 text-[11.5px] leading-5 text-muted-foreground">
              以 Qdrant 过滤计数与数据库 indexed_at 分别展示，不用“已核验”冒充“可检索”。
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
