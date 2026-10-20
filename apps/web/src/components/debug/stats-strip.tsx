"use client";

import * as React from "react";
import {
  Activity,
  BadgeDollarSign,
  Clock,
  Coins,
  Gauge,
  ShieldAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { DebugStats } from "@/lib/api/debug-types";
import { formatMs, formatPercent } from "@/lib/utils";

function StatTile({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "default" | "warning";
}) {
  return (
    <div className="surface-card flex items-center gap-3 px-4 py-3">
      <span
        className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${
          tone === "warning"
            ? "bg-warning-soft text-warning"
            : "bg-primary-soft text-primary-soft-fg"
        }`}
      >
        <Icon className="size-4" />
      </span>
      <div className="min-w-0">
        <p className="text-[11.5px] font-medium text-subtle-foreground">{label}</p>
        <p className="mt-0.5 text-[17px] font-semibold leading-6 tabular-nums text-foreground">
          {value}
        </p>
        {hint && <p className="mt-0.5 truncate text-[11px] text-subtle-foreground">{hint}</p>}
      </div>
    </div>
  );
}

export function StatsStrip({
  stats,
  loading,
  windowHours,
}: {
  stats: DebugStats | undefined;
  loading?: boolean;
  windowHours: number;
}) {
  if (loading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} className="h-[68px] w-full" />
        ))}
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="surface-card px-4 py-6 text-center text-[13px] text-muted-foreground">
        暂无遥测数据。
      </div>
    );
  }

  const models = Object.entries(stats.models);

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <StatTile
        label="查询数"
        value={String(stats.queries)}
        hint={`最近 ${windowHours} 小时`}
        icon={Activity}
      />
      <StatTile
        label="证据不足拒答"
        value={formatPercent(stats.refusal_rate)}
        hint={`${stats.refusals} / ${stats.queries} 次`}
        icon={ShieldAlert}
        tone={stats.refusal_rate > 0.2 ? "warning" : "default"}
      />
      <StatTile
        label="P95 检索耗时"
        value={formatMs(stats.p95_retrieval_ms)}
        hint={`均值 ${formatMs(stats.avg_retrieval_ms)}`}
        icon={Gauge}
      />
      <StatTile
        label="P95 总耗时"
        value={formatMs(stats.p95_total_ms)}
        hint={`均值 ${formatMs(stats.avg_total_ms)}`}
        icon={Clock}
      />
      <StatTile
        label="Token / 成本"
        value={`${stats.prompt_tokens + stats.completion_tokens}`}
        hint={`${models[0]?.[0] ?? "—"} · $${stats.cost_usd.toFixed(4)}`}
        icon={models.length ? Coins : BadgeDollarSign}
      />
    </div>
  );
}
