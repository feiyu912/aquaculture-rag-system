"use client";

import * as React from "react";
import { X } from "lucide-react";

import { CitationSidebar, type ReaderCitation } from "@/components/reader/citation-sidebar";
import { Button } from "@/components/ui/button";

/**
 * Below the `xl` breakpoint the citation list becomes an overlay drawer so
 * the PDF canvas keeps the full width of the viewport.
 */
export function CitationSidebarDrawer({
  open,
  citations,
  activeCitationId,
  onSelect,
  onOpenConversation,
  onClose,
}: {
  open: boolean;
  citations: ReaderCitation[];
  activeCitationId: string | null;
  onSelect: (citation: ReaderCitation) => void;
  onOpenConversation?: (citation: ReaderCitation) => void;
  onClose: () => void;
}) {
  return (
    <div
      className={`fixed inset-0 z-40 xl:hidden ${
        open ? "pointer-events-auto" : "pointer-events-none"
      }`}
      aria-hidden={!open}
    >
      <div
        className={`absolute inset-0 bg-foreground/30 transition-opacity duration-200 ${
          open ? "opacity-100" : "opacity-0"
        }`}
        onClick={onClose}
      />
      <div
        className={`absolute inset-y-0 right-0 flex w-[min(90vw,340px)] flex-col border-l border-border bg-surface shadow-xl transition-transform duration-250 ease-soft ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex h-12 shrink-0 items-center justify-end border-b border-border px-3">
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="关闭引用面板">
            <X className="size-4" />
          </Button>
        </div>
        <CitationSidebar
          className="flex-1 border-l-0"
          citations={citations}
          activeCitationId={activeCitationId}
          onSelect={onSelect}
          onOpenConversation={onOpenConversation}
        />
      </div>
    </div>
  );
}
