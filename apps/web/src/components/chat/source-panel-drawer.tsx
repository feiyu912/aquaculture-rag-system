"use client";

import * as React from "react";
import { X } from "lucide-react";

import { SourceCard } from "@/components/chat/source-card";
import { Button } from "@/components/ui/button";
import type { Source } from "@/lib/api/types";

/**
 * Below the `lg` breakpoint the citation panel becomes an overlay drawer so
 * the conversation keeps the full width of the viewport.
 */
export function SourcePanelDrawer({
  open,
  sources,
  selectedIndex,
  onSelect,
  onOpenPdf,
  onClose,
}: {
  open: boolean;
  sources: Source[];
  selectedIndex: number | null;
  onSelect: (index: number) => void;
  onOpenPdf?: (source: Source) => void;
  onClose: () => void;
}) {
  return (
    <div
      className={`fixed inset-0 z-40 xl:hidden ${open ? "pointer-events-auto" : "pointer-events-none"}`}
      aria-hidden={!open}
    >
      <div
        className={`absolute inset-0 bg-foreground/30 transition-opacity duration-200 ${
          open ? "opacity-100" : "opacity-0"
        }`}
        onClick={onClose}
      />
      <div
        className={`absolute inset-y-0 right-0 flex w-[min(90vw,360px)] flex-col border-l border-border bg-surface shadow-xl transition-transform duration-250 ease-soft ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
          <span className="text-[13px] font-semibold text-foreground">引用来源</span>
          <span className="rounded-full bg-surface-inset px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
            {sources.length}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            onClick={onClose}
            aria-label="关闭引用面板"
          >
            <X className="size-4" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
          {sources.length === 0 ? (
            <p className="px-2 py-8 text-center text-[12.5px] leading-5 text-subtle-foreground">
              本次回答暂无可展示的引用来源。
            </p>
          ) : (
            <div className="flex flex-col gap-2.5">
              {sources.map((source) => (
                <SourceCard
                  key={`${source.document_id}-${source.index}`}
                  source={source}
                  active={selectedIndex === source.index}
                  onSelect={onSelect}
                  onOpenPdf={onOpenPdf}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
