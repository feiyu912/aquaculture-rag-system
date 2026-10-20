"use client";

import * as React from "react";
import {
  Anchor,
  CheckCircle2,
  CircleSlash,
  Cpu,
  Database,
  Filter,
  GitMerge,
  Layers,
  ListTree,
  Minimize2,
  Route,
  Search,
  ShieldCheck,
  Sparkles,
  Split,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface StageDefinition {
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  state: "on" | "off" | "skipped";
  detail?: string;
}

const STATE_STYLE: Record<StageDefinition["state"], { badge: string; text: string }> = {
  on: { badge: "bg-success-soft text-success", text: "text-success" },
  off: { badge: "bg-surface-inset text-subtle-foreground", text: "text-subtle-foreground" },
  skipped: { badge: "bg-warning-soft text-warning", text: "text-warning" },
};

const STATE_LABEL: Record<StageDefinition["state"], string> = {
  on: "已启用",
  off: "未启用",
  skipped: "本次未触发",
};

export function PipelineStages({
  stages,
  className,
}: {
  stages: StageDefinition[];
  className?: string;
}) {
  return (
    <ol className={cn("relative space-y-0.5", className)}>
      {stages.map((stage, index) => {
        const Icon = stage.icon;
        const style = STATE_STYLE[stage.state];
        const isLast = index === stages.length - 1;

        return (
          <li key={stage.key} className="relative flex gap-3 pb-3 last:pb-0">
            {!isLast && (
              <span className="absolute left-[13px] top-7 h-[calc(100%-18px)] w-px bg-border" />
            )}
            <span
              className={cn(
                "relative z-10 flex size-[27px] shrink-0 items-center justify-center rounded-lg border border-border bg-surface",
                stage.state === "off" && "opacity-60",
              )}
            >
              <Icon className={cn("size-3.5", style.text)} />
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex items-center gap-2">
                <span className="truncate text-[12.5px] font-medium text-foreground">
                  {stage.label}
                </span>
                <span
                  className={cn(
                    "ml-auto shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                    style.badge,
                  )}
                >
                  {STATE_LABEL[stage.state]}
                </span>
              </div>
              {stage.detail && (
                <p className="mt-0.5 truncate font-mono text-[10.5px] text-subtle-foreground">
                  {stage.detail}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export const STAGE_ICONS = {
  anchor: Anchor,
  ir: ListTree,
  planner: Sparkles,
  decompose: Split,
  graph: GitMerge,
  filters: Filter,
  dense: Database,
  sparse: Search,
  rrf: Layers,
  rerank: Route,
  gate: ShieldCheck,
  contextual: Minimize2,
  llm: Cpu,
};

export function StageBadge({ state }: { state: StageDefinition["state"] }) {
  return (
    <Badge
      variant={
        state === "on" ? "success" : state === "skipped" ? "warning" : "neutral"
      }
      className="gap-1"
    >
      {state === "on" ? (
        <CheckCircle2 className="size-3" />
      ) : (
        <CircleSlash className="size-3" />
      )}
      {STATE_LABEL[state]}
    </Badge>
  );
}
