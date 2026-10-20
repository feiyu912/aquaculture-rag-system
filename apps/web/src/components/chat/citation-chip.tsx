"use client";

import * as React from "react";
import { FileText } from "lucide-react";

import { cn } from "@/lib/utils";

export function CitationChip({
  index,
  active,
  hasSource,
  onSelect,
}: {
  index: number;
  active?: boolean;
  hasSource?: boolean;
  onSelect?: (index: number) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect?.(index)}
      title={hasSource ? `查看来源 S${index}` : `来源 S${index} 不在本次证据中`}
      className={cn(
        "mx-[1px] inline-flex h-[18px] min-w-[26px] items-center justify-center rounded-[5px] border px-1 align-baseline text-[11px] font-semibold leading-none transition-colors duration-150",
        hasSource
          ? active
            ? "border-primary-btn bg-primary-btn text-primary-fg"
            : "border-primary-200 bg-primary-soft text-primary-soft-fg hover:border-primary-400 hover:bg-primary-100"
          : "cursor-not-allowed border-danger/30 bg-danger-soft text-danger line-through",
      )}
    >
      <FileText className="mr-0.5 size-[10px]" strokeWidth={2.4} />
      {index}
    </button>
  );
}
