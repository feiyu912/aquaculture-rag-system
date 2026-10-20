"use client";

import * as React from "react";
import { FileText, Quote, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn, truncate } from "@/lib/utils";

export interface ReaderCitation {
  id: string;
  source_index: number;
  quote: string;
  page: number | null;
  bbox: { page: number; bbox: [number, number, number, number] } | null;
  question: string;
  answer_preview: string;
  cited_at: string;
  message_id: string;
  session_id: string;
  version_no: number | null;
}

export function CitationSidebar({
  citations,
  activeCitationId,
  onSelect,
  onOpenConversation,
  className,
}: {
  citations: ReaderCitation[];
  activeCitationId: string | null;
  onSelect: (citation: ReaderCitation) => void;
  onOpenConversation?: (citation: ReaderCitation) => void;
  className?: string;
}) {
  const [query, setQuery] = React.useState("");

  const filtered = React.useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return citations;
    return citations.filter((citation) =>
      `${citation.quote} ${citation.question}`.toLowerCase().includes(keyword),
    );
  }, [citations, query]);

  return (
    <aside
      className={cn(
        "flex h-full min-h-0 flex-col border-l border-border bg-surface",
        className,
      )}
    >
      <div className="shrink-0 space-y-2.5 border-b border-border px-3.5 py-3">
        <div className="flex items-center gap-2">
          <Quote className="size-3.5 text-primary-600" />
          <span className="text-[13px] font-semibold text-foreground">引用高亮</span>
          <span className="ml-auto rounded-full bg-surface-inset px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
            {citations.length}
          </span>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索引用内容"
            className="h-8 pl-8 text-[12.5px]"
            aria-label="搜索引用"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {filtered.length === 0 ? (
          <div className="px-2 py-10 text-center">
            <FileText className="mx-auto size-5 text-subtle-foreground/60" />
            <p className="mt-2 text-[12.5px] leading-5 text-subtle-foreground">
              {citations.length === 0
                ? "该文档还没有被任何回答引用过。"
                : "没有匹配的引用。"}
            </p>
          </div>
        ) : (
          <ul className="flex flex-col gap-2.5">
            {filtered.map((citation) => {
              const active = citation.id === activeCitationId;
              return (
                <li key={citation.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(citation)}
                    className={cn(
                      "w-full rounded-xl border px-3 py-2.5 text-left transition-all duration-200 ease-soft",
                      active
                        ? "border-primary-300 bg-primary-soft shadow-sm"
                        : "border-border bg-surface hover:border-border-strong hover:shadow-sm",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "flex size-5 shrink-0 items-center justify-center rounded-full border text-[10.5px] font-semibold tabular-nums",
                          active
                            ? "border-primary-btn bg-primary-btn text-primary-fg"
                            : "border-border bg-surface-muted text-muted-foreground",
                        )}
                      >
                        {citation.source_index}
                      </span>
                      {citation.page ? (
                        <Badge variant="neutral">第 {citation.page} 页</Badge>
                      ) : null}
                      {citation.version_no ? (
                        <Badge variant="outline">v{citation.version_no}</Badge>
                      ) : null}
                    </div>
                    <p className="mt-2 line-clamp-4 text-[12.5px] leading-[1.65] text-muted-foreground">
                      {citation.quote}
                    </p>
                    <p className="mt-2 truncate text-[11px] text-subtle-foreground">
                      来自提问：{truncate(citation.question, 22)}
                    </p>
                  </button>

                  {onOpenConversation && (
                    <Button
                      variant="link"
                      size="xs"
                      className="mt-1 h-auto px-1 text-[11px]"
                      onClick={() => onOpenConversation(citation)}
                    >
                      查看原始回答
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
