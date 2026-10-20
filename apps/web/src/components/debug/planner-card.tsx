"use client";

import * as React from "react";
import { AlertTriangle, ListChecks, Sparkles } from "lucide-react";

import { Section } from "@/components/debug/section";
import { Badge } from "@/components/ui/badge";
import type { PlannerTrace } from "@/lib/api/debug-types";
import type { QueryTrace } from "@/lib/api/types";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-subtle-foreground">{label}</dt>
      <dd className="mt-0.5 truncate font-medium text-foreground">{value}</dd>
    </div>
  );
}

/**
 * Planner panel.
 *
 * Shows exactly what the backend reported: the rule IR, the planner trace
 * (including the deliberate "skipped" case) and the plan's sub-questions,
 * tasks, constraints and assumptions. Nothing is inferred or faked.
 */
export function PlannerCard({ trace }: { trace: QueryTrace }) {
  const planner: PlannerTrace | null | undefined = trace.llm_planner;
  const ir = trace.query_ir;

  if (!planner || !planner.enabled) {
    return (
      <Section title="LLM Planner（NL2IR）">
        <div className="flex items-start gap-2.5 rounded-xl border border-border bg-surface-muted px-3.5 py-3">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-subtle-foreground" />
          <div>
            <p className="text-[13px] font-semibold text-foreground">未启用</p>
            <p className="mt-0.5 text-[12.5px] leading-5 text-muted-foreground">
              本次请求使用规则版 Query IR。LLM Planner 需要在服务端开启
              <code className="mx-1 rounded bg-surface px-1 py-0.5 font-mono text-[11px]">
                ENABLE_LLM_PLANNER
              </code>
              并配置可用的 LLM 网关。
            </p>
          </div>
        </div>
      </Section>
    );
  }

  const skipped = planner.skipped;
  const usedLlm = planner.used_llm === true;

  const state = usedLlm
    ? { label: "本次由 LLM 生成", variant: "success" as const }
    : skipped
      ? { label: "本次跳过 Planner", variant: "warning" as const }
      : planner.error
        ? { label: "回退到规则 IR", variant: "warning" as const }
        : { label: "规则 IR", variant: "neutral" as const };

  return (
    <Section
      title="LLM Planner（NL2IR）"
      hint={
        usedLlm
          ? "本次由 LLM 生成"
          : skipped
            ? "简单问题命中规则 IR，未调用模型"
            : "回退到规则 IR"
      }
      action={
        <Badge variant={state.variant} className="gap-1">
          {usedLlm ? <Sparkles className="size-3" /> : null}
          {state.label}
        </Badge>
      }
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12.5px]">
        <Field label="耗时" value={formatMs(planner.duration_ms)} />
        <Field label="尝试次数" value={String(planner.attempts ?? 1)} />
        <Field label="硬过滤" value={planner.hard_filter ?? "无"} />
        <Field
          label="子问题"
          value={planner.subquestions?.length ? String(planner.subquestions.length) : "—"}
        />
      </dl>

      {skipped && (
        <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-surface-muted px-2.5 py-2 text-[11.5px] leading-5 text-muted-foreground">
          <ListChecks className="mt-0.5 size-3 shrink-0" />
          跳过原因：<code className="font-mono">{skipped}</code>
          —— 规则 IR 已能覆盖该问题，调用模型只会增加延迟。
        </p>
      )}

      {planner.error && (
        <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-warning-soft px-2.5 py-2 text-[11.5px] leading-5 text-warning">
          <AlertTriangle className="mt-0.5 size-3 shrink-0" />
          planner 错误：{planner.error}
        </p>
      )}

      {planner.subquestions && planner.subquestions.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] text-subtle-foreground">Planner 子问题</p>
          <ol className="mt-1.5 space-y-1">
            {planner.subquestions.map((question, index) => (
              <li key={question} className="flex gap-2 text-[12px] leading-5 text-foreground">
                <span className="tabular-nums text-subtle-foreground">{index + 1}.</span>
                <span>{question}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {planner.tasks && planner.tasks.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] text-subtle-foreground">Planner 任务</p>
          <ul className="mt-1.5 space-y-1">
            {planner.tasks.map((task, index) => (
              <li key={index} className="text-[11.5px] leading-5 text-muted-foreground">
                <span className="font-mono text-[10.5px] text-foreground">
                  {String(task.question ?? task.facet ?? `任务 ${index + 1}`)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {planner.constraints && planner.constraints.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] text-subtle-foreground">Planner 约束</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {planner.constraints.map((constraint) => (
              <Badge key={`${constraint.name}-${constraint.value}`} variant="neutral">
                {constraint.name}: {constraint.value}
                <span className="ml-1 opacity-60">({constraint.strength})</span>
              </Badge>
            ))}
          </div>
        </div>
      )}

      {planner.assumptions && planner.assumptions.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] text-subtle-foreground">Planner 假设</p>
          <ul className="mt-1.5 space-y-1">
            {planner.assumptions.map((assumption) => (
              <li key={assumption} className="text-[12px] leading-5 text-muted-foreground">
                · {assumption}
              </li>
            ))}
          </ul>
        </div>
      )}

      {ir?.planner_source === "llm" && (
        <p className="mt-3 rounded-lg bg-success-soft px-2.5 py-2 text-[11.5px] leading-5 text-success">
          本次 Query IR 由 LLM Planner 生成（置信度{" "}
          {ir.planner_confidence?.toFixed(2) ?? "未提供"}）。
        </p>
      )}
    </Section>
  );
}

function formatMs(value?: number | null) {
  if (value === null || value === undefined) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}
