"use client";

import * as React from "react";
import { Database, FileQuestion, Loader2, RefreshCw, Search, X } from "lucide-react";

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
import { useQaLibraryPage, useQaLibrarySummary } from "@/hooks/use-qa-library";
import { datasetLabel, type QaLibraryItem } from "@/lib/api/qa-library";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 20;

function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function QaDetailDialog({ item, onClose }: { item: QaLibraryItem | null; onClose: () => void }) {
  return (
    <Dialog open={Boolean(item)} onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        {item ? (
          <>
            <DialogHeader>
              <DialogTitle className="pr-6 text-[15px] leading-6">{item.question}</DialogTitle>
              <DialogDescription className="text-[11.5px]">
                {datasetLabel(item.dataset_id)}
                {item.license ? ` · ${item.license}` : ""}
              </DialogDescription>
            </DialogHeader>
            <div className="mt-2 rounded-lg border border-border bg-surface-inset/60 px-3.5 py-3 text-[13px] leading-6 text-foreground whitespace-pre-wrap">
              {item.answer}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {item.topics.map((topic) => (
                <Badge key={topic} variant="neutral">
                  {topic}
                </Badge>
              ))}
              {item.species.map((species) => (
                <Badge key={species} variant="neutral">
                  {species}
                </Badge>
              ))}
            </div>
            <p className="mt-3 text-[11px] text-subtle-foreground">
              数据来源：{item.dataset_id} · 记录 ID {item.original_id}
            </p>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export function QaLibraryPanel() {
  const [query, setQuery] = React.useState("");
  const [topic, setTopic] = React.useState<string>("");
  const [offset, setOffset] = React.useState(0);
  const [detail, setDetail] = React.useState<QaLibraryItem | null>(null);
  const debouncedQuery = useDebounced(query.trim());

  React.useEffect(() => {
    setOffset(0);
  }, [debouncedQuery, topic]);

  const { data: summary, isLoading: summaryLoading } = useQaLibrarySummary();
  const pageQuery = React.useMemo(
    () => ({
      q: debouncedQuery || undefined,
      topic: topic || undefined,
      limit: PAGE_SIZE,
      offset,
    }),
    [debouncedQuery, topic, offset],
  );
  const { data: page, isLoading, isFetching, isError, error, refetch } = useQaLibraryPage(
    pageQuery,
    summary?.available === true,
  );

  if (summaryLoading) {
    return (
      <div className="flex items-center gap-2 px-2 py-10 text-[12.5px] text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> 正在加载问答数据…
      </div>
    );
  }

  if (!summary?.available) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface px-5 py-10 text-center">
        <FileQuestion className="mx-auto size-6 text-subtle-foreground" />
        <p className="mt-2 text-[13px] font-medium text-foreground">问答数据尚未构建完成</p>
        <p className="mt-1 text-[12px] text-muted-foreground">
          构建完成后将在此展示 HF 问答记忆的浏览与相似问题检索。
        </p>
      </div>
    );
  }

  const total = page?.total ?? 0;
  const hasPrev = offset > 0;
  const hasNext = offset + (page?.items.length ?? 0) < total;
  const from = total === 0 ? 0 : offset + 1;
  const to = offset + (page?.items.length ?? 0);

  return (
    <div>
      <section className="rounded-xl border border-border bg-surface px-4 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-[14px] font-semibold text-foreground">
              <Database className="size-4 text-primary-600" />
              HF QA Memory
            </h2>
            <p className="mt-1 max-w-[640px] text-[12px] leading-5 text-muted-foreground">
              用于相似问题检索与回答辅助：匹配相近的既有问题，提供候选回答与术语线索；最终回答由原始文献证据支持。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11.5px]">
            <span className="rounded-lg bg-surface-inset px-2.5 py-1 tabular-nums text-foreground">
              共 {summary.total.toLocaleString()} 条
            </span>
            {summary.datasets.map((dataset) => (
              <span
                key={dataset.dataset_id}
                className="rounded-lg bg-surface-inset px-2.5 py-1 text-muted-foreground"
              >
                {datasetLabel(dataset.dataset_id)} · {dataset.count.toLocaleString()}
              </span>
            ))}
          </div>
        </div>

        {summary.topics.length > 0 ? (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setTopic("")}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-[11px] transition-colors",
                topic === ""
                  ? "border-primary-500/40 bg-primary-500/10 text-primary-700"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              全部主题
            </button>
            {summary.topics.map((entry) => (
              <button
                key={entry.topic}
                type="button"
                onClick={() => setTopic(entry.topic === topic ? "" : entry.topic)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-[11px] transition-colors",
                  topic === entry.topic
                    ? "border-primary-500/40 bg-primary-500/10 text-primary-700"
                    : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {entry.topic}
                <span className="ml-1 tabular-nums opacity-70">{entry.count}</span>
              </button>
            ))}
          </div>
        ) : null}
      </section>

      <section className="mt-5">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[260px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
            <Input
              id="qa-library-search"
              name="qa-library-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="相似问题检索，例如：南美白对虾池塘亚硝酸盐升高怎么办？"
              className="h-9 pl-8 pr-8 text-[12.5px]"
            />
            {query ? (
              <button
                type="button"
                aria-label="清空检索"
                onClick={() => setQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-subtle-foreground hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            ) : null}
          </div>
          <Button variant="ghost" size="sm" onClick={() => void refetch()} disabled={isFetching}>
            {isFetching ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            刷新
          </Button>
        </div>

        {isError ? (
          <div className="mt-3 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-[12.5px] text-danger">
            问答数据加载失败：{error instanceof Error ? error.message : "接口不可用"}
          </div>
        ) : isLoading ? (
          <div className="flex items-center gap-2 px-1 py-8 text-[12.5px] text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> 正在检索…
          </div>
        ) : (page?.items.length ?? 0) === 0 ? (
          <div className="mt-3 rounded-xl border border-border bg-surface px-4 py-8 text-center text-[12.5px] text-muted-foreground">
            {debouncedQuery ? "没有找到相近的问题" : "暂无问答数据"}
          </div>
        ) : (
          <ul className="mt-3 divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
            {page?.items.map((item) => (
              <li key={item.original_id}>
                <button
                  type="button"
                  onClick={() => setDetail(item)}
                  className="block w-full px-4 py-3 text-left transition-colors hover:bg-surface-inset/60"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-medium text-foreground">{item.question}</span>
                    {typeof item.score === "number" ? (
                      <span className="text-[10.5px] tabular-nums text-subtle-foreground">
                        相近度 {(item.score * 60).toFixed(1)}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-muted-foreground">{item.answer}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10.5px] text-subtle-foreground">
                    <span>{datasetLabel(item.dataset_id)}</span>
                    {item.topics.slice(0, 3).map((tag) => (
                      <span key={tag} className="rounded bg-surface-inset px-1.5 py-0.5 text-muted-foreground">
                        {tag}
                      </span>
                    ))}
                    {item.species.slice(0, 3).map((tag) => (
                      <span key={tag} className="rounded bg-surface-inset px-1.5 py-0.5 text-muted-foreground">
                        {tag}
                      </span>
                    ))}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}

        {total > 0 ? (
          <div className="mt-3 flex items-center justify-between text-[11.5px] text-muted-foreground">
            <span className="tabular-nums">
              {debouncedQuery ? `共 ${total} 条相近结果` : `共 ${total.toLocaleString()} 条 · 第 ${from}–${to} 条`}
            </span>
            <div className="flex items-center gap-1.5">
              <Button
                variant="outline"
                size="sm"
                disabled={!hasPrev || isFetching}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                上一页
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!hasNext || isFetching}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                下一页
              </Button>
            </div>
          </div>
        ) : null}
      </section>

      <QaDetailDialog item={detail} onClose={() => setDetail(null)} />
    </div>
  );
}