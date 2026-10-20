"use client";

import * as React from "react";
import { ArrowUpRight, FileText, Layers } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Source } from "@/lib/api/types";
import { cn, truncate } from "@/lib/utils";

export function SourceCard({
  source,
  active,
  onSelect,
  onOpenPdf,
}: {
  source: Source;
  active?: boolean;
  onSelect?: (index: number) => void;
  onOpenPdf?: (source: Source) => void;
}) {
  const heading = source.heading_path?.length
    ? source.heading_path.join(" › ")
    : null;

  return (
    <article
      id={`source-S${source.index}`}
      onClick={() => onSelect?.(source.index)}
      className={cn(
        "group cursor-pointer rounded-xl border bg-surface p-3.5 transition-all duration-200 ease-soft",
        active
          ? "border-primary-300 bg-primary-50/45 shadow-sm"
          : "border-border hover:border-border-strong hover:shadow-sm",
      )}
    >
      <header className="flex items-start gap-2.5">
        <span
          className={cn(
            "mt-0.5 flex size-[22px] shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold tabular-nums transition-colors",
            active
              ? "border-primary-btn bg-primary-btn text-primary-fg"
              : "border-primary-300 bg-primary-soft text-primary-soft-fg",
          )}
        >
          {source.index}
        </span>
        <div className="min-w-0 flex-1">
          <h4 className="line-clamp-2 text-[13px] font-semibold leading-5 text-foreground">
            {source.title}
          </h4>
          {heading && (
            <p className="mt-0.5 truncate text-[11.5px] text-subtle-foreground">{heading}</p>
          )}
        </div>
      </header>

      <p className="mt-2.5 line-clamp-4 text-[12.5px] leading-[1.65] text-muted-foreground">
        {source.quote}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {source.page ? (
          <Badge variant="neutral" className="gap-1">
            <FileText className="size-3" />
            第 {source.page} 页
          </Badge>
        ) : null}
        {source.version_no ? <Badge variant="neutral">v{source.version_no}</Badge> : null}
        {source.species?.length ? (
          <Badge variant="neutral" className="gap-1">
            <Layers className="size-3" />
            {truncate(source.species.join("、"), 14)}
          </Badge>
        ) : null}
        {source.location ? (
          <Badge variant="outline" className="font-mono text-[10px]">
            bbox {source.location.bbox.map((v) => Math.round(v)).join(",")}
          </Badge>
        ) : null}
      </div>

      {onOpenPdf && (
        <Button
          variant="link"
          size="xs"
          className="mt-2.5 h-auto px-0 text-[11.5px] font-medium"
          onClick={(event) => {
            event.stopPropagation();
            onOpenPdf(source);
          }}
        >
          在 PDF 原文中定位
          <ArrowUpRight className="size-3" />
        </Button>
      )}
    </article>
  );
}
