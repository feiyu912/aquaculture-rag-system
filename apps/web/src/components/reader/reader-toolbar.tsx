"use client";

import * as React from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Maximize2,
  Minus,
  Plus,
  Quote,
  Ruler,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export function ReaderToolbar({
  title,
  versionNo,
  page,
  numPages,
  zoom,
  onZoomChange,
  onPageChange,
  onFitWidth,
  onToggleCitations,
  citationsOpen,
  citationCount,
  downloadUrl,
  highlightLabel,
}: {
  title: string;
  versionNo?: number | null;
  page: number;
  numPages: number;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  onPageChange: (page: number) => void;
  onFitWidth: () => void;
  onToggleCitations?: () => void;
  citationsOpen?: boolean;
  citationCount?: number;
  downloadUrl: string;
  highlightLabel?: string | null;
}) {
  const [draft, setDraft] = React.useState(String(page));

  React.useEffect(() => {
    setDraft(String(page));
  }, [page]);

  const clamp = (value: number) => Math.min(Math.max(value, 1), Math.max(numPages, 1));

  return (
    <div className="no-scrollbar flex h-12 shrink-0 items-center gap-2 overflow-x-auto border-b border-border bg-surface px-3 sm:gap-3 sm:px-4">
      <div className="flex min-w-0 shrink items-center gap-2">
        <span className="max-w-[9rem] truncate text-[13px] font-semibold text-foreground sm:max-w-none">
          {title}
        </span>
        {versionNo ? <Badge variant="neutral">v{versionNo}</Badge> : null}
        {highlightLabel ? (
          <Badge variant="default" className="hidden gap-1 sm:inline-flex">
            <Ruler className="size-3" />
            {highlightLabel}
          </Badge>
        ) : null}
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface-muted p-0.5">
          <Tooltip delayDuration={300}>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="缩小"
                onClick={() => onZoomChange(Math.max(0.4, Number((zoom - 0.15).toFixed(2))))}
                disabled={zoom <= 0.4}
              >
                <Minus className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>缩小</TooltipContent>
          </Tooltip>

          <span className="hidden w-12 text-center text-[12px] font-medium tabular-nums text-muted-foreground sm:inline">
            {Math.round(zoom * 100)}%
          </span>

          <Tooltip delayDuration={300}>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="放大"
                onClick={() => onZoomChange(Math.min(3, Number((zoom + 0.15).toFixed(2))))}
                disabled={zoom >= 3}
              >
                <Plus className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>放大</TooltipContent>
          </Tooltip>

          <Tooltip delayDuration={300}>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="适应宽度"
                onClick={onFitWidth}
              >
                <Maximize2 className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>适应宽度</TooltipContent>
          </Tooltip>
        </div>

        <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface-muted p-0.5">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="上一页"
            onClick={() => onPageChange(clamp(page - 1))}
            disabled={page <= 1}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const value = Number.parseInt(draft, 10);
              if (Number.isFinite(value)) onPageChange(clamp(value));
            }}
            className="flex items-center gap-1 px-1"
          >
            <Input
              value={draft}
              onChange={(event) => setDraft(event.target.value.replace(/\D/g, ""))}
              inputMode="numeric"
              aria-label={`第 ${page} 页，共 ${numPages} 页`}
              className="h-7 w-9 border-none bg-transparent px-1 text-center text-[12px] font-medium tabular-nums shadow-none focus-visible:ring-1"
            />
            <span className="text-[12px] tabular-nums text-subtle-foreground">
              / {numPages}
            </span>
          </form>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="下一页"
            onClick={() => onPageChange(clamp(page + 1))}
            disabled={page >= numPages}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>

        <Button variant="ghost" size="icon-sm" asChild>
          <a href={downloadUrl} target="_blank" rel="noreferrer" aria-label="下载原文">
            <Download className="size-4" />
          </a>
        </Button>

        {onToggleCitations && (
          <Button
            variant={citationsOpen ? "secondary" : "ghost"}
            size="icon-sm"
            onClick={onToggleCitations}
            aria-label="引用来源面板"
            className="relative"
          >
            <Quote className="size-4" />
            {citationCount ? (
              <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-primary-btn text-[9px] font-semibold tabular-nums text-primary-fg">
                {citationCount}
              </span>
            ) : null}
          </Button>
        )}
      </div>
    </div>
  );
}

export function ZoomBadge({ value }: { value: number }) {
  return (
    <span className={cn("text-[11px] tabular-nums text-muted-foreground")}>
      {Math.round(value * 100)}%
    </span>
  );
}
