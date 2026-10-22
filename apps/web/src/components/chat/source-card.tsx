"use client";

import * as React from "react";
import { ArrowUpRight, FileText, Globe2, HelpCircle, Layers, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Source } from "@/lib/api/types";
import { MEDIA_TYPE_LABELS, unavailableReasonLabel } from "@/lib/labels";
import { cn, truncate } from "@/lib/utils";

export function SourceCard({
  source,
  active,
  onSelect,
  onOpenSource,
}: {
  source: Source;
  active?: boolean;
  onSelect?: (index: number) => void;
  onOpenSource?: (source: Source) => void;
}) {
  const heading = source.heading_path?.length ? source.heading_path.join(" › ") : null;
  const unavailable = source.available === false;
  const isPdf = source.media_type === "pdf";
  const isHtml = source.media_type === "html";
  const bbox = isPdf ? source.location?.bbox : undefined;
  const pdfLocations = isPdf
    ? (source.locations ?? []).filter(
        (entry) => typeof entry.page === "number" && Array.isArray(entry.bbox),
      )
    : [];
  const pageCounts = pdfLocations.reduce<Map<number, number>>((counts, entry) => {
    const page = entry.page as number;
    counts.set(page, (counts.get(page) ?? 0) + 1);
    return counts;
  }, new Map());
  const locationPages = [...pageCounts.keys()].sort((a, b) => a - b);
  const pageEnd =
    source.page_end ??
    (locationPages.length > 0 ? locationPages[locationPages.length - 1] : source.page);
  const contiguousPages =
    locationPages.length > 2 &&
    pageEnd !== null &&
    pageEnd !== undefined &&
    pageEnd - (source.page ?? locationPages[0]) + 1 === locationPages.length;
  const pageLabel =
    locationPages.length === 0
      ? `${source.page}`
      : contiguousPages
        ? `${source.page ?? locationPages[0]}–${pageEnd}`
        : locationPages.join("、");
  const pageSummary = locationPages
    .map((page) => `第${page}页${(pageCounts.get(page) ?? 0) > 1 ? `（${pageCounts.get(page)}处）` : ""}`)
    .join("、");

  return (
    <article
      id={`source-S${source.index}`}
      onClick={() => onSelect?.(source.index)}
      className={cn(
        "group cursor-pointer rounded-xl border bg-surface p-3.5 transition-all duration-200 ease-soft",
        active
          ? "border-primary-300 bg-primary-50/45 shadow-sm"
          : "border-border hover:border-border-strong hover:shadow-sm",
        unavailable && "opacity-80",
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
        <Badge variant="neutral" className="gap-1">
          {isHtml ? (
            <Globe2 className="size-3" />
          ) : source.media_type === "faq" ? (
            <HelpCircle className="size-3" />
          ) : (
            <FileText className="size-3" />
          )}
          {MEDIA_TYPE_LABELS[source.media_type] ?? source.media_type}
        </Badge>
        {isPdf && source.page ? (
          <Badge variant="neutral" className="gap-1">
            第 {pageLabel} 页
          </Badge>
        ) : null}
        {isPdf && pdfLocations.length > 1 ? (
          <Badge variant="outline">{pdfLocations.length} 处定位</Badge>
        ) : null}
        {isHtml ? (
          <Badge variant="neutral" className="gap-1">
            网页快照
            {typeof source.location?.paragraph === "number"
              ? ` · 段落 ${source.location.paragraph}`
              : ""}
          </Badge>
        ) : null}
        {source.media_type === "faq" ? (
          <Badge variant="neutral">
            {source.available === false ? "FAQ 来源不可用" : "FAQ 条目（已核验）"}
          </Badge>
        ) : null}
        {source.version_no ? <Badge variant="neutral">v{source.version_no}</Badge> : null}
        {source.supplemental ? <Badge variant="info">原文不足补充</Badge> : null}
        {source.species?.length ? (
          <Badge variant="neutral" className="gap-1">
            <Layers className="size-3" />
            {truncate(source.species.join("、"), 14)}
          </Badge>
        ) : null}
        {isPdf && !unavailable && bbox && pdfLocations.length <= 1 ? (
          <Badge variant="outline" className="font-mono text-[10px]">
            bbox {bbox.map((value) => Math.round(value)).join(",")}
          </Badge>
        ) : null}
      </div>

      {isPdf && pdfLocations.length > 1 ? (
        <p className="mt-2 text-[11px] leading-4 text-subtle-foreground">
          引用定位：{pageSummary}
        </p>
      ) : null}

      {unavailable ? (
        <p className="mt-2.5 flex items-start gap-1.5 text-[11px] leading-4 text-warning">
          <ShieldAlert className="mt-0.5 size-3 shrink-0" />
          {unavailableReasonLabel(source.unavailable_reason)}
        </p>
      ) : null}

      {onOpenSource && (
        <Button
          variant="link"
          size="xs"
          className="mt-2.5 h-auto px-0 text-[11.5px] font-medium"
          disabled={unavailable}
          onClick={(event) => {
            event.stopPropagation();
            onOpenSource(source);
          }}
        >
          {unavailable
            ? "来源不可访问"
            : isPdf
              ? "在 PDF 原文中定位"
              : isHtml
                ? "查看网页快照"
                : "查看 FAQ 与支撑原文"}
          <ArrowUpRight className="size-3" />
        </Button>
      )}
    </article>
  );
}
