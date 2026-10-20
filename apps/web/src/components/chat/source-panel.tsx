"use client";

import * as React from "react";
import { PanelRightClose } from "lucide-react";

import { SourceCard } from "@/components/chat/source-card";
import { Button } from "@/components/ui/button";
import type { Source } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export function SourcePanel({
  sources,
  selectedIndex,
  onSelect,
  onOpenPdf,
  onClose,
  className,
}: {
  sources: Source[];
  selectedIndex: number | null;
  onSelect: (index: number) => void;
  onOpenPdf?: (source: Source) => void;
  onClose?: () => void;
  className?: string;
}) {
  const cardRefs = React.useRef(new Map<number, HTMLElement>());

  React.useEffect(() => {
    if (selectedIndex === null) return;
    const node = cardRefs.current.get(selectedIndex);
    node?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedIndex]);

  return (
    <aside
      className={cn(
        "flex h-full w-[320px] shrink-0 flex-col border-l border-border bg-surface",
        className,
      )}
    >
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
        <span className="text-[13px] font-semibold text-foreground">引用来源</span>
        <span className="rounded-full bg-surface-inset px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
          {sources.length}
        </span>
        {onClose && (
          <Button
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            onClick={onClose}
            aria-label="收起引用面板"
          >
            <PanelRightClose className="size-4" />
          </Button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {sources.length === 0 ? (
          <p className="px-2 py-8 text-center text-[12.5px] leading-5 text-subtle-foreground">
            本次回答暂无可展示的引用来源。
          </p>
        ) : (
          <div className="flex flex-col gap-2.5">
            {sources.map((source) => (
              <div
                key={`${source.document_id}-${source.index}`}
                ref={(node) => {
                  if (node) cardRefs.current.set(source.index, node);
                }}
              >
                <SourceCard
                  source={source}
                  active={selectedIndex === source.index}
                  onSelect={onSelect}
                  onOpenPdf={onOpenPdf}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
