"use client";

import * as React from "react";
import { ArrowRight, Database, GitMerge, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface CandidateColumn {
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  ids: string[];
  accent: string;
  hint?: string;
}

function shortId(id: string) {
  return id.replace(/-/g, "").slice(0, 8);
}

export function CandidateBoard({
  dense,
  sparse,
  fused,
  evidenceChunkIds,
}: {
  dense: string[];
  sparse: string[];
  fused: string[];
  evidenceChunkIds: string[];
}) {
  const denseSet = React.useMemo(() => new Set(dense), [dense]);
  const sparseSet = React.useMemo(() => new Set(sparse), [sparse]);
  const fusedSet = React.useMemo(() => new Set(fused), [fused]);
  const evidenceSet = React.useMemo(() => new Set(evidenceChunkIds), [evidenceChunkIds]);

  const overlap = React.useMemo(
    () => dense.filter((id) => sparseSet.has(id)).length,
    [dense, sparseSet],
  );
  const denseOnly = dense.filter((id) => !sparseSet.has(id)).length;
  const sparseOnly = sparse.filter((id) => !denseSet.has(id)).length;

  const columns: CandidateColumn[] = [
    {
      key: "dense",
      label: "Dense 召回",
      icon: Database,
      ids: dense,
      accent: "bg-primary-400",
      hint: `BGE-M3 · top ${dense.length}`,
    },
    {
      key: "sparse",
      label: "BM25 召回",
      icon: Search,
      ids: sparse,
      accent: "bg-warning",
      hint: `稀疏向量 · top ${sparse.length}`,
    },
    {
      key: "fused",
      label: "RRF 融合",
      icon: GitMerge,
      ids: fused,
      accent: "bg-primary-300",
      hint: `融合候选 ${fused.length}`,
    },
  ];

  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-3">
        <Metric label="Dense ∩ BM25" value={overlap} hint="两路共同命中" />
        <Metric label="仅 Dense 命中" value={denseOnly} hint="语义独有" />
        <Metric label="仅 BM25 命中" value={sparseOnly} hint="关键词独有" />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {columns.map((column) => {
          const Icon = column.icon;
          return (
            <div
              key={column.key}
              className="instrument-panel overflow-hidden"
            >
              <div className="flex items-center gap-2 border-b border-instrument-border px-3 py-2.5">
                <Icon className="size-3.5 text-instrument-muted" />
                <span className="text-[12.5px] font-semibold text-instrument-foreground">
                  {column.label}
                </span>
                <span className="ml-auto text-[11px] tabular-nums text-instrument-muted">
                  {column.ids.length}
                </span>
              </div>
              <div className="p-2">
                {column.ids.length === 0 ? (
                  <p className="px-2 py-6 text-center text-[11.5px] text-instrument-muted">
                    该通道本次没有候选
                  </p>
                ) : (
                  <ol className="space-y-1">
                    {column.ids.slice(0, 12).map((id, index) => {
                      const inDense = denseSet.has(id);
                      const inSparse = sparseSet.has(id);
                      const inFused = fusedSet.has(id);
                      const inEvidence = evidenceSet.has(id);
                      return (
                        <li
                          key={id}
                          className={cn(
                            "flex items-center gap-2 rounded-md px-2 py-1.5 text-[11.5px]",
                            inEvidence
                              ? "bg-primary-500/18 text-instrument-foreground"
                              : "text-instrument-muted",
                          )}
                        >
                          <span className="w-5 shrink-0 text-right tabular-nums opacity-70">
                            {index + 1}
                          </span>
                          <span
                            className={cn(
                              "h-1 w-8 shrink-0 rounded-full",
                              inEvidence ? column.accent : "bg-instrument-border",
                            )}
                            style={{
                              width: `${Math.max(
                                8,
                                32 *
                                  (1 - index / Math.max(column.ids.length, 1)) *
                                  (inEvidence ? 1 : 0.45),
                              )}px`,
                            }}
                          />
                          <span className="truncate font-mono text-[10.5px]">
                            {shortId(id)}
                          </span>
                          <span className="ml-auto flex shrink-0 gap-1">
                            {inDense && column.key !== "dense" && (
                              <span className="rounded bg-primary-500/20 px-1 text-[9.5px] font-medium text-primary-300">
                                D
                              </span>
                            )}
                            {inSparse && column.key !== "sparse" && (
                              <span className="rounded bg-warning/20 px-1 text-[9.5px] font-medium text-warning">
                                B
                              </span>
                            )}
                            {inFused && column.key !== "fused" && (
                              <span className="rounded bg-instrument-border px-1 text-[9.5px] font-medium text-instrument-foreground">
                                F
                              </span>
                            )}
                          </span>
                        </li>
                      );
                    })}
                    {column.ids.length > 12 && (
                      <li className="px-2 pt-1 text-[10.5px] text-instrument-muted">
                        还有 {column.ids.length - 12} 条未展示
                      </li>
                    )}
                  </ol>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: number;
  hint: string;
}) {
  return (
    <div className="instrument-panel flex items-center gap-3 px-3.5 py-2.5">
      <span className="text-[18px] font-semibold tabular-nums text-instrument-foreground">
        {value}
      </span>
      <span className="min-w-0">
        <span className="block text-[11.5px] font-medium text-instrument-foreground">
          {label}
        </span>
        <span className="block text-[10.5px] text-instrument-muted">{hint}</span>
      </span>
    </div>
  );
}

export function RerankDelta({
  before,
  after,
  mappable,
}: {
  before: { chunkId: string; label: string }[];
  after: { chunkId: string; label: string }[];
  /** False for traces recorded before sources carried a chunk id. */
  mappable: boolean;
}) {
  if (after.length === 0) {
    return (
      <p className="text-[12.5px] text-muted-foreground">本次请求没有产生最终证据。</p>
    );
  }

  if (!mappable) {
    return (
      <div className="space-y-3">
        <p className="rounded-lg border border-border bg-surface-muted px-3 py-2.5 text-[12.5px] leading-5 text-muted-foreground">
          该请求的记录生成于来源携带 chunk_id 之前，无法把 RRF 候选与最终证据逐条对应。
          下方仅展示重排后的最终顺序；新的请求会显示完整的排名变化。
        </p>
        <ol className="space-y-1.5">
          {after.map((item, index) => (
            <li
              key={item.chunkId}
              className="flex items-center gap-2.5 rounded-lg border border-border px-3 py-2 text-[12.5px]"
            >
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary-soft text-[10.5px] font-semibold tabular-nums text-primary-soft-fg">
                {index + 1}
              </span>
              <span className="truncate text-foreground">{item.label}</span>
            </li>
          ))}
        </ol>
      </div>
    );
  }

  const beforeIndex = new Map(before.map((item, index) => [item.chunkId, index + 1]));
  const afterIndex = new Map(after.map((item, index) => [item.chunkId, index + 1]));

  const rows = after.map((item, index) => {
    const from = beforeIndex.get(item.chunkId);
    const to = index + 1;
    const delta = from === undefined ? null : from - to;
    return { ...item, from, to, delta };
  });

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="grid grid-cols-[28px_1fr_96px_96px_64px] items-center gap-2 border-b border-border bg-surface-muted px-3 py-2 text-[11px] font-medium uppercase tracking-[0.06em] text-subtle-foreground">
        <span>#</span>
        <span>来源</span>
        <span>RRF 前</span>
        <span>重排后</span>
        <span className="text-right">变化</span>
      </div>
      <ul className="divide-y divide-border">
        {rows.map((row) => (
          <li
            key={row.chunkId}
            className="grid grid-cols-[28px_1fr_96px_96px_64px] items-center gap-2 px-3 py-2 text-[12px]"
          >
            <span className="tabular-nums text-subtle-foreground">{row.to}</span>
            <span className="truncate text-foreground">{row.label}</span>
            <span className="tabular-nums text-muted-foreground">
              {row.from ? `#${row.from}` : "—"}
            </span>
            <span className="tabular-nums text-muted-foreground">#{row.to}</span>
            <span className="text-right">
              {row.delta === null ? (
                <Badge variant="neutral">新进</Badge>
              ) : row.delta > 0 ? (
                <Badge variant="success">↑ {row.delta}</Badge>
              ) : row.delta < 0 ? (
                <Badge variant="warning">↓ {Math.abs(row.delta)}</Badge>
              ) : (
                <Badge variant="neutral">持平</Badge>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ArrowMarker() {
  return <ArrowRight className="size-3.5 text-subtle-foreground" />;
}
