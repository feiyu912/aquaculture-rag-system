"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { Activity, CircleAlert, ExternalLink, Loader2, PanelLeft } from "lucide-react";

import { ThemeToggle } from "@/components/layout/theme-toggle";
import { useShell } from "@/components/layout/shell-context";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useHealth } from "@/hooks/use-health";
import { API_BASE_URL } from "@/lib/api/client";
import { NAV_ITEMS } from "@/lib/navigation";
import { cn } from "@/lib/utils";

export function TopBar() {
  const pathname = usePathname();
  const { data: health, isError } = useHealth();
  const {
    hasContext,
    contextLabel,
    contextCollapsed,
    setContextCollapsed,
    setMobileContextOpen,
  } = useShell();

  const current =
    NAV_ITEMS.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`)) ??
    NAV_ITEMS[0];

  const healthy = health?.status === "ok";
  const degraded = health?.status === "degraded";
  const checking = !health && !isError;

  const healthLabel = isError
    ? "后端离线"
    : healthy
      ? "服务正常"
      : degraded
        ? "部分降级"
        : "检查中";

  const healthTone = isError
    ? "border-danger/25 bg-danger-soft text-danger"
    : degraded
      ? "border-warning/25 bg-warning-soft text-warning"
      : healthy
        ? "border-success/25 bg-success-soft text-success"
        : "border-border bg-surface-muted text-muted-foreground";

  return (
    <header className="z-30 flex h-[var(--topbar-height)] w-full shrink-0 items-center gap-3 border-b border-border bg-surface/85 px-4 backdrop-blur-md">
      {hasContext && (
        <Button
          variant="ghost"
          size="icon-sm"
          className="-ml-1 shrink-0"
          aria-label={contextCollapsed ? `展开${contextLabel}` : `收起${contextLabel}`}
          onClick={() => {
            if (window.matchMedia("(max-width: 1023px)").matches) {
              setMobileContextOpen(true);
            } else {
              setContextCollapsed(!contextCollapsed);
            }
          }}
        >
          <PanelLeft className="size-4" />
        </Button>
      )}

      <div className="flex min-w-0 items-baseline gap-2.5">
        <h1 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-foreground">
          {current.label}
        </h1>
        <span className="hidden truncate text-[12.5px] text-subtle-foreground sm:inline">
          {current.description}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <Tooltip delayDuration={250}>
          <TooltipTrigger asChild>
            <span
              className={cn(
                "hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition-colors md:inline-flex",
                healthTone,
              )}
            >
              {isError ? (
                <CircleAlert className="size-3.5" />
              ) : checking ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Activity className="size-3.5" />
              )}
              {healthLabel}
            </span>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-xs">
            {isError ? (
              <span>无法连接 {API_BASE_URL}</span>
            ) : (
              <div className="flex flex-col gap-1 py-0.5">
                {Object.entries(health?.components ?? {}).map(([key, value]) => (
                  <span key={key} className="flex items-center justify-between gap-4">
                    <span className="text-muted-foreground">{key}</span>
                    <span
                      className={cn(
                        "text-[11px]",
                        value === "ok" ? "text-success" : "text-warning",
                      )}
                    >
                      {value}
                    </span>
                  </span>
                ))}
                <span className="mt-1 flex items-center justify-between gap-4 border-t border-border pt-1">
                  <span className="text-muted-foreground">embedding</span>
                  <span className="text-[11px] text-foreground">{health?.embedding_model}</span>
                </span>
                <span className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">reranker</span>
                  <span className="text-[11px] text-foreground">{health?.reranker_model}</span>
                </span>
                <span className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">llm</span>
                  <span className="text-[11px] text-foreground">
                    {health?.llm_provider}
                    {health?.llm_configured ? "" : "（未配置）"}
                  </span>
                </span>
              </div>
            )}
          </TooltipContent>
        </Tooltip>

        <Button variant="ghost" size="icon-sm" asChild>
          <a href={`${API_BASE_URL}/docs`} target="_blank" rel="noreferrer" aria-label="OpenAPI 文档">
            <ExternalLink className="size-4" />
          </a>
        </Button>

        <ThemeToggle />
      </div>
    </header>
  );
}
