"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  Cpu,
  FileText,
  Gauge,
  KeyRound,
  Layers,
  ListTree,
  Loader2,
  Route as RouteIcon,
  Search,
  ShieldCheck,
  Sparkles,
  Timer,
} from "lucide-react";

import { CandidateBoard, RerankDelta } from "@/components/debug/candidate-board";
import {
  PipelineStages,
  STAGE_ICONS,
  type StageDefinition,
} from "@/components/debug/pipeline-stages";
import { PlannerCard } from "@/components/debug/planner-card";
import { QueryIrCard } from "@/components/debug/query-ir-card";
import { SourceAwareCard } from "@/components/debug/source-aware-card";
import { RawTrace, Section } from "@/components/debug/section";
import { StatsStrip } from "@/components/debug/stats-strip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { API_BASE_URL } from "@/lib/api/client";
import { debugApi } from "@/lib/api/documents";
import type { DebugStats } from "@/lib/api/debug-types";
import type { QueryTrace } from "@/lib/api/types";
import { cn, formatMs, formatPercent } from "@/lib/utils";

export function DebugWorkspace({ initialRequestId = "" }: { initialRequestId?: string }) {
  const searchParams = useSearchParams();
  const [requestId, setRequestId] = React.useState(initialRequestId);
  const [activeRequestId, setActiveRequestId] = React.useState(initialRequestId);

  const { data: stats, isLoading: statsLoading } = useQuery<DebugStats>({
    queryKey: ["debug-stats", 24],
    queryFn: () =>
      fetch(`${API_BASE_URL}/api/debug/stats?hours=24`).then((response) => {
        if (!response.ok) throw new Error("遥测数据加载失败");
        return response.json();
      }),
  });

  const { data: trace, isLoading, error } = useQuery<QueryTrace>({
    queryKey: ["debug-trace", activeRequestId],
    queryFn: () => debugApi.trace(activeRequestId),
    enabled: Boolean(activeRequestId),
    retry: false,
  });

  const stages = React.useMemo(() => buildStages(trace), [trace]);

  return (
    <div className="flex h-full min-h-0">
      <div className="scroll-contain min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1180px] space-y-5 px-4 py-6 sm:px-6 sm:py-8">
          <StatsStrip stats={stats} loading={statsLoading} windowHours={24} />

          <Section
            title="检索链路"
            hint={trace ? `request_id ${trace.request_id.slice(0, 12)}…` : "输入 request_id 查看单次请求"}
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label
                  htmlFor="request-id"
                  className="mb-1.5 block text-[11.5px] font-medium text-muted-foreground"
                >
                  request_id
                </label>
                <Input
                  id="request-id"
                  value={requestId}
                  onChange={(event) => setRequestId(event.target.value.trim())}
                  placeholder="从智能问答页点击「检索详情」可自动填入"
                  className="font-mono text-[12.5px]"
                />
              </div>
              <Button
                onClick={() => setActiveRequestId(requestId)}
                disabled={!requestId || isLoading}
              >
                {isLoading ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
                加载 Trace
              </Button>
            </div>

            {error && (
              <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-danger/25 bg-danger-soft px-3.5 py-3">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" />
                <div>
                  <p className="text-[13px] font-semibold text-foreground">
                    未找到该请求的 Trace
                  </p>
                  <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                    {error instanceof Error ? error.message : "查询失败"}
                  </p>
                </div>
              </div>
            )}

            {trace && (
              <div className="mt-4 rounded-xl border border-border bg-surface-muted p-4">
                <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-subtle-foreground">
                  查询
                </p>
                <p className="mt-1.5 text-[14px] font-medium leading-6 text-foreground">
                  {trace.question}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Badge variant="default" className="gap-1">
                    <RouteIcon className="size-3" />
                    {trace.retrieval_config?.adaptive_route ?? "rag"}
                  </Badge>
                  <Badge variant="neutral" className="gap-1">
                    <Layers className="size-3" />
                    {trace.retrieval_config?.retrieval_mode ?? "—"}
                  </Badge>
                  <Badge variant="neutral" className="gap-1">
                    <Cpu className="size-3" />
                    {trace.model ?? "—"}
                  </Badge>
                  {trace.cost_usd ? (
                    <Badge variant="neutral">${trace.cost_usd.toFixed(6)}</Badge>
                  ) : null}
                  <Badge variant="neutral" className="gap-1">
                    <KeyRound className="size-3" />
                    {trace.active_versions.length} 个生效版本
                  </Badge>
                </div>

                <div className="mt-4 grid gap-2 sm:grid-cols-4">
                  <Timing label="Dense" value={trace.timings?.dense_ms} />
                  <Timing label="BM25" value={trace.timings?.sparse_ms} />
                  <Timing label="检索合计" value={trace.timings?.retrieval_ms} />
                  <Timing label="总耗时" value={trace.timings?.total_ms} />
                </div>
              </div>
            )}
          </Section>

          {isLoading && (
            <div className="space-y-3">
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-64 w-full" />
            </div>
          )}

          {trace && (
            <>
              <div className="grid gap-5 lg:grid-cols-2">
                <QueryIrCard trace={trace} />
                <PlannerCard trace={trace} />
              </div>

              <SourceAwareCard trace={trace} />

              <Section
                title="候选与融合"
                hint="D = Dense 命中 · B = BM25 命中 · F = 进入 RRF 融合"
                tone="instrument"
              >
                <div className="rounded-xl bg-instrument/40 p-1">
                  <CandidateBoard
                    dense={trace.rankings?.dense ?? []}
                    sparse={trace.rankings?.sparse ?? []}
                    fused={trace.fused ?? []}
                    evidenceChunkIds={(trace.evidence ?? []).map((source) =>
                      source.child_chunk_id ?? source.chunk_id ?? "",
                    )}
                  />
                </div>
              </Section>

              <Section
                title="重排与最终证据"
                hint={
                  trace.retrieval_config?.retrieval_mode === "hybrid_rerank"
                    ? `reranker: ${trace.retrieval_config?.reranker ?? "—"}`
                    : "本次未启用 Reranker（仅 RRF 排序）"
                }
              >
                <RerankDelta
                  mappable={(trace.evidence ?? []).some((source) =>
                    Boolean(source.child_chunk_id ?? source.chunk_id),
                  )}
                  before={(trace.fused ?? []).map((chunkId, index) => {
                    const source = (trace.evidence ?? []).find(
                      (item) => (item.child_chunk_id ?? item.chunk_id) === chunkId,
                    );
                    return {
                      chunkId,
                      label: source
                        ? `${source.title}${source.page ? ` · 第 ${source.page} 页` : ""}`
                        : `候选 #${index + 1}`,
                    };
                  })}
                  after={(trace.evidence ?? []).map((source) => ({
                    chunkId: source.child_chunk_id ?? source.chunk_id ?? source.source_id,
                    label: `${source.title}${source.page ? ` · 第 ${source.page} 页` : ""}`,
                  }))}
                />
              </Section>

              <div className="grid gap-5 lg:grid-cols-2">
                <GateCard trace={trace} />
                <EvidenceCard trace={trace} />
              </div>

              <RawTrace value={trace} />
            </>
          )}
        </div>
      </div>

      <aside className="hidden w-[var(--context-width)] shrink-0 flex-col overflow-y-auto border-l border-border bg-surface lg:flex">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-[13px] font-semibold text-foreground">执行阶段</h2>
          <p className="mt-0.5 text-[11.5px] text-subtle-foreground">
            来自本次 Trace 的真实配置
          </p>
        </div>
        <div className="px-4 py-4">
          <PipelineStages stages={stages} />
        </div>
      </aside>
    </div>
  );
}

function Timing({ label, value }: { label: string; value?: number | null }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2">
      <p className="flex items-center gap-1.5 text-[11px] text-subtle-foreground">
        <Timer className="size-3" />
        {label}
      </p>
      <p className="mt-0.5 text-[14px] font-semibold tabular-nums text-foreground">
        {formatMs(value)}
      </p>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-subtle-foreground">{label}</dt>
      <dd className="mt-0.5 truncate font-medium text-foreground">{value}</dd>
    </div>
  );
}

function GateCard({ trace }: { trace: QueryTrace }) {
  const gate = trace.gate;
  const sufficient = gate?.sufficient;

  return (
    <Section title="证据门槛" hint="词面规则 · 非 NLI">
      <div
        className={cn(
          "flex items-center gap-2.5 rounded-xl border px-3.5 py-3",
          sufficient
            ? "border-success/25 bg-success-soft"
            : "border-warning/25 bg-warning-soft",
        )}
      >
        {sufficient ? (
          <CheckCircle2 className="size-4 shrink-0 text-success" />
        ) : (
          <AlertTriangle className="size-4 shrink-0 text-warning" />
        )}
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-foreground">
            {sufficient ? "证据充分" : "证据不足，已触发拒答"}
          </p>
          <p className="mt-0.5 font-mono text-[11.5px] text-muted-foreground">
            reason: {gate?.reason ?? "—"}
          </p>
        </div>
        <div className="ml-auto text-right">
          <p className="text-[11px] text-subtle-foreground">覆盖率</p>
          <p className="text-[15px] font-semibold tabular-nums text-foreground">
            {formatPercent(gate?.coverage ?? 0)}
          </p>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12.5px]">
        <Field label="命中词数" value={String(gate?.matched_terms?.length ?? 0)} />
        <Field label="查询词数" value={String(gate?.query_terms?.length ?? 0)} />
        <Field label="命中权重" value={String(gate?.matched_weight ?? 0)} />
        <Field label="总权重" value={String(gate?.total_weight ?? 0)} />
      </dl>

      {gate?.missing_terms?.length ? (
        <div className="mt-3">
          <p className="text-[11px] text-subtle-foreground">缺失词</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {gate.missing_terms.map((term) => (
              <Badge key={term} variant="warning">
                {term}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
    </Section>
  );
}

function EvidenceCard({ trace }: { trace: QueryTrace }) {
  const evidence = trace.evidence ?? [];
  const report = trace.citation_check;

  return (
    <Section title="最终证据与引用" hint={`${evidence.length} 条`}>
      {evidence.length === 0 ? (
        <p className="text-[12.5px] text-muted-foreground">本次请求没有产生证据。</p>
      ) : (
        <ul className="space-y-2">
          {evidence.map((source) => (
            <li
              key={source.source_id}
              className="rounded-lg border border-border bg-surface-muted px-3 py-2.5"
            >
              <div className="flex items-center gap-2">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary-soft text-[10.5px] font-semibold tabular-nums text-primary-soft-fg">
                  {source.index}
                </span>
                <span className="truncate text-[12.5px] font-medium text-foreground">
                  {source.title}
                </span>
                {source.page ? (
                  <span className="shrink-0 text-[11px] text-subtle-foreground">
                    第 {source.page} 页
                  </span>
                ) : null}
              </div>
              <p className="mt-1.5 line-clamp-2 text-[11.5px] leading-5 text-muted-foreground">
                {source.quote}
              </p>
            </li>
          ))}
        </ul>
      )}

      {report && (
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3 text-[11.5px]">
          <Badge variant={report.valid ? "success" : "danger"}>
            引用{report.valid ? "有效" : "含无效编号"}
          </Badge>
          <span className="text-muted-foreground">
            事实引用覆盖率 {formatPercent(report.coverage)}
          </span>
          {report.claim_summary ? (
            <span className="text-muted-foreground">
              · 声明支持 {report.claim_summary.supported}/{report.claim_summary.total}
              （词面 v0）
            </span>
          ) : null}
        </div>
      )}
    </Section>
  );
}

function buildStages(trace: QueryTrace | undefined): StageDefinition[] {
  const config = trace?.retrieval_config;
  const modules = config?.adaptive_modules ?? {};
  const mode = config?.retrieval_mode ?? "hybrid";
  const planner = trace?.llm_planner;
  const aware =
    trace?.source_aware_retrieval ??
    (trace?.retrieval_config?.source_aware_retrieval as
      | import("@/lib/api/debug-types").SourceAwareTrace
      | null
      | undefined);

  return [
    {
      key: "ir",
      label: "规则 Query IR",
      icon: STAGE_ICONS.ir,
      state: "on",
      detail: trace?.query_ir?.strategy ?? "simple",
    },
    {
      key: "planner",
      label: "LLM Planner",
      icon: STAGE_ICONS.planner,
      state: planner?.enabled ? (planner.used_llm ? "on" : "skipped") : "off",
      detail: planner?.enabled
        ? planner.used_llm
          ? `${formatMs(planner.duration_ms)} · LLM`
          : planner.skipped
            ? `跳过：${planner.skipped}`
            : planner.error
              ? `回退规则 IR（${planner.error}）`
              : "规则 IR"
        : "未启用",
    },
    {
      key: "source-aware",
      label: "按来源锚定",
      icon: STAGE_ICONS.anchor,
      state: aware?.active ? "on" : aware ? "skipped" : "off",
      detail: aware?.active
        ? (aware.cited ?? []).map((a) => a.code).join("、")
        : aware?.reason
          ? `未生效：${aware.reason}`
          : aware
            ? "未触发（问题未同时引用两个标准）"
            : "未启用",
    },
    {
      key: "decompose",
      label: "问题分解",
      icon: STAGE_ICONS.decompose,
      state: modules.decomposition ? "on" : "off",
      detail: config?.query_decomposition ? "多 facet 子查询" : "未启用",
    },
    {
      key: "graph",
      label: "领域图扩展",
      icon: STAGE_ICONS.graph,
      state: modules.graph ? "on" : "off",
      detail: config?.graph_expansion ? "一跳扩展" : "未启用（需先写入种子图）",
    },
    {
      key: "dense",
      label: "Dense 召回",
      icon: STAGE_ICONS.dense,
      state: mode === "dense" || mode === "hybrid" || mode === "hybrid_rerank" ? "on" : "off",
      detail: `${config?.embedding ?? "—"} · top ${config?.dense_top_k ?? "—"}`,
    },
    {
      key: "sparse",
      label: "BM25 召回",
      icon: STAGE_ICONS.sparse,
      state: mode === "bm25" || mode === "hybrid" || mode === "hybrid_rerank" ? "on" : "off",
      detail: `jieba+custom · top ${config?.bm25_top_k ?? "—"}`,
    },
    {
      key: "rrf",
      label: "RRF 融合",
      icon: STAGE_ICONS.rrf,
      state: "on",
      detail: `k=${config?.rrf_k ?? "—"} · 候选 ${trace?.fused_count ?? 0}`,
    },
    {
      key: "rerank",
      label: "Reranker 重排",
      icon: STAGE_ICONS.rerank,
      state: mode === "hybrid_rerank" ? "on" : "off",
      detail:
        mode === "hybrid_rerank"
          ? `${config?.reranker ?? config?.reranker_model ?? "—"} · top ${config?.rerank_top_k ?? "—"}`
          : "未启用（仅 RRF 排序）",
    },
    {
      key: "gate",
      label: "证据门槛",
      icon: STAGE_ICONS.gate,
      state: "on",
      detail: trace?.gate?.sufficient ? "通过" : `未通过 · ${trace?.gate?.reason ?? "—"}`,
    },
    {
      key: "contextual",
      label: "Contextual 检索",
      icon: STAGE_ICONS.contextual,
      state: config?.contextual_retrieval ? "on" : "off",
      detail: config?.contextual_retrieval ? "索引辅助文本" : "未启用",
    },
    {
      key: "llm",
      label: "生成模型",
      icon: STAGE_ICONS.llm,
      state: "on",
      detail: trace?.model ?? "—",
    },
  ];
}

export function DebugIcons() {
  return (
    <div className="flex gap-2 text-subtle-foreground">
      <Activity className="size-4" />
      <Boxes className="size-4" />
      <FileText className="size-4" />
      <Gauge className="size-4" />
      <ListTree className="size-4" />
      <ShieldCheck className="size-4" />
      <ArrowRight className="size-4" />
    </div>
  );
}
