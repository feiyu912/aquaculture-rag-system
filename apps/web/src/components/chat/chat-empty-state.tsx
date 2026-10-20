"use client";

import * as React from "react";
import { BookOpenText, Droplets, PanelRightOpen, Sparkles, Waves } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const EXAMPLES = [
  {
    icon: Droplets,
    label: "溶解氧",
    question: "中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？",
  },
  {
    icon: Waves,
    label: "酸碱度",
    question: "凡纳滨对虾养殖水质的酸碱度要求是什么？",
  },
  {
    icon: BookOpenText,
    label: "水质管理",
    question: "池塘养殖常用的水质调控指标有哪些？",
  },
];

export function ChatEmptyState({
  onPick,
  hasDocuments,
}: {
  onPick: (question: string) => void;
  hasDocuments: boolean;
}) {
  return (
    <div className="mx-auto flex w-full max-w-[620px] flex-col items-center px-2 py-10 text-center">
      <div className="relative mb-5">
        <div className="absolute inset-0 -z-10 blur-2xl">
          <div className="mx-auto size-24 rounded-full bg-primary-500/18" />
        </div>
        <div className="flex size-12 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-800 text-white shadow-lg shadow-primary-900/15">
          <Waves className="size-6" strokeWidth={2} />
        </div>
      </div>

      <h2 className="text-[19px] font-semibold tracking-[-0.015em] text-foreground">
        向水产养殖知识库提问
      </h2>
      <p className="mt-2 max-w-md text-[13.5px] leading-6 text-muted-foreground">
        系统会基于 BGE-M3 向量检索与 BM25 关键词召回的混合结果作答，
        并为每条结论标注可点击的来源引用，可直接跳转到 PDF 原文核对。
      </p>

      <div className="mt-7 w-full">
        <div className="mb-2.5 flex items-center justify-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-subtle-foreground">
          <Sparkles className="size-3" />
          试试这些问题
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          {EXAMPLES.map((example) => {
            const Icon = example.icon;
            return (
              <button
                key={example.question}
                type="button"
                onClick={() => onPick(example.question)}
                className={cn(
                  "group flex flex-col items-start gap-2 rounded-xl border border-border bg-surface px-3.5 py-3 text-left shadow-xs transition-all duration-200 ease-soft",
                  "hover:-translate-y-0.5 hover:border-primary-300 hover:shadow-md",
                )}
              >
                <span className="flex size-7 items-center justify-center rounded-lg bg-primary-50 text-primary-700 transition-colors group-hover:bg-primary-100">
                  <Icon className="size-3.5" />
                </span>
                <span className="text-[12.5px] font-medium leading-5 text-foreground">
                  {example.label}
                </span>
                <span className="line-clamp-2 text-[11.5px] leading-[1.55] text-muted-foreground">
                  {example.question}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {!hasDocuments && (
        <p className="mt-7 rounded-lg border border-warning/25 bg-warning-soft px-3.5 py-2.5 text-[12.5px] text-warning">
          知识库中还没有可用文档，请先到「知识库」上传 PDF 并等待解析完成。
        </p>
      )}
    </div>
  );
}

export function ChatToolbar({
  status,
  retrievalMode,
  onRetrievalModeChange,
  sourceCount,
  panelOpen,
  onTogglePanel,
}: {
  status: { stage: string; sources: number; sufficient: boolean } | null;
  retrievalMode: string;
  onRetrievalModeChange: (mode: "dense" | "bm25" | "hybrid" | "hybrid_rerank") => void;
  sourceCount: number;
  panelOpen: boolean;
  onTogglePanel: () => void;
}) {
  const statusLabel = status
    ? status.sufficient
      ? `已检索 ${status.sources} 条证据 · 生成中`
      : "证据不足，正在生成说明"
    : null;

  return (
    <div className="flex h-11 shrink-0 items-center gap-3 border-b border-border bg-surface/70 px-4 backdrop-blur-sm sm:px-6">
      <span className="truncate text-[12px] text-muted-foreground">
        {statusLabel ?? "就绪"}
      </span>

      <div className="ml-auto flex items-center gap-2">
        <div className="flex items-center rounded-lg border border-border bg-surface p-0.5">
          {(
            [
              { value: "hybrid", label: "混合" },
              { value: "hybrid_rerank", label: "重排" },
              { value: "dense", label: "Dense" },
              { value: "bm25", label: "BM25" },
            ] as const
          ).map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => onRetrievalModeChange(option.value)}
              className={cn(
                "rounded-md px-2 py-1 text-[11.5px] font-medium transition-colors duration-150",
                retrievalMode === option.value
                  ? "bg-primary-btn text-primary-fg shadow-xs"
                  : "text-muted-foreground hover:bg-surface-muted hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>

        <Button
          variant={panelOpen ? "secondary" : "ghost"}
          size="icon-sm"
          onClick={onTogglePanel}
          aria-label="引用来源面板"
          className="relative"
        >
          <PanelRightOpen className="size-4" />
          {sourceCount > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-primary-700 text-[9px] font-semibold tabular-nums text-white">
              {sourceCount}
            </span>
          )}
        </Button>
      </div>
    </div>
  );
}
