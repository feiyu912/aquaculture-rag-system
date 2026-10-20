"use client";

import * as React from "react";
import { FileText, Layers } from "lucide-react";

import { cn } from "@/lib/utils";

export function PageList({
  numPages,
  currentPage,
  citedPages,
  onSelect,
}: {
  numPages: number;
  currentPage: number;
  citedPages: Set<number>;
  onSelect: (page: number) => void;
}) {
  const listRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>(`[data-page="${currentPage}"]`);
    node?.scrollIntoView({ block: "nearest" });
  }, [currentPage]);

  if (numPages === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center">
        <p className="text-[12.5px] text-subtle-foreground">文档加载中…</p>
      </div>
    );
  }

  return (
    <div ref={listRef} className="scroll-contain h-full overflow-y-auto px-2.5 py-3">
      <p className="px-1.5 pb-2 text-[11px] font-medium uppercase tracking-[0.06em] text-subtle-foreground">
        页面 · {numPages}
      </p>
      <ul className="space-y-0.5">
        {Array.from({ length: numPages }, (_, index) => index + 1).map((page) => {
          const active = page === currentPage;
          const cited = citedPages.has(page);
          return (
            <li key={page}>
              <button
                type="button"
                data-page={page}
                onClick={() => onSelect(page)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[12.5px] transition-colors duration-150",
                  active
                    ? "bg-primary-soft font-medium text-primary-soft-fg"
                    : "text-muted-foreground hover:bg-surface-muted hover:text-foreground",
                )}
              >
                <span
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-md border text-[11px] font-medium tabular-nums",
                    active
                      ? "border-primary-btn bg-primary-btn text-primary-fg"
                      : "border-border bg-surface text-muted-foreground",
                  )}
                >
                  {page}
                </span>
                {cited ? (
                  <span className="inline-flex items-center gap-1 text-[11px] text-primary-600">
                    <Layers className="size-3" />
                    有引用
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-[11px] text-subtle-foreground/70">
                    <FileText className="size-3" />
                    原文
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
