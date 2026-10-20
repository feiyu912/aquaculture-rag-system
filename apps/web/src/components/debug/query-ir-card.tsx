"use client";

import * as React from "react";
import { AlertTriangle, ListTree, Sparkles } from "lucide-react";

import { Section } from "@/components/debug/section";
import { Badge } from "@/components/ui/badge";
import type { QueryIR, QueryTrace } from "@/lib/api/types";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-subtle-foreground">{label}</dt>
      <dd className="mt-0.5 truncate font-medium text-foreground">{value}</dd>
    </div>
  );
}

export function QueryIrCard({ trace }: { trace: QueryTrace }) {
  const ir = trace.query_ir;
  if (!ir) {
    return (
      <Section title="Typed Query IR" hint="规则解析">
        <p className="text-[12.5px] text-muted-foreground">
          本次请求没有记录 Query IR。
        </p>
      </Section>
    );
  }

  const fromLlm = ir.planner_source === "llm";

  return (
    <Section
      title="Typed Query IR"
      hint={fromLlm ? "LLM Planner 生成" : "规则 v1 · 非 LLM"}
      action={
        <Badge variant={fromLlm ? "success" : "neutral"} className="gap-1">
          {fromLlm ? <Sparkles className="size-3" /> : <ListTree className="size-3" />}
          {fromLlm ? "LLM" : "规则"}
        </Badge>
      }
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12.5px]">
        <Field label="意图" value={ir.intent} />
        <Field label="策略" value={ir.strategy} />
        <Field label="品种" value={ir.species?.join("、") || "—"} />
        <Field label="硬过滤" value={ir.species_filter ?? "未启用"} />
        <Field label="养殖阶段" value={ir.growth_stage?.join("、") || "—"} />
        <Field label="水质指标" value={ir.water_parameters?.join("、") || "—"} />
        <Field label="请求年份" value={ir.requested_year ? String(ir.requested_year) : "—"} />
        <Field
          label="现行法规"
          value={ir.requires_current_regulation ? "需要（缺元数据）" : "否"}
        />
        <Field label="规则置信度" value={ir.confidence?.toFixed(2) ?? "—"} />
        <Field
          label="Planner 置信度"
          value={ir.planner_confidence != null ? ir.planner_confidence.toFixed(2) : "未启用"}
        />
      </dl>

      {ir.rewritten_query && ir.rewritten_query !== ir.original_question && (
        <div className="mt-3 rounded-lg border border-border bg-surface-muted px-3 py-2">
          <p className="text-[11px] text-subtle-foreground">改写后的查询</p>
          <p className="mt-1 text-[12.5px] leading-5 text-foreground">{ir.rewritten_query}</p>
        </div>
      )}

      {ir.planner_subquestions?.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] text-subtle-foreground">Planner 子问题</p>
          <ol className="mt-1.5 space-y-1">
            {ir.planner_subquestions.map((question, index) => (
              <li key={question} className="flex gap-2 text-[12px] leading-5 text-foreground">
                <span className="tabular-nums text-subtle-foreground">{index + 1}.</span>
                <span>{question}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {ir.planner_constraints?.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] text-subtle-foreground">Planner 约束</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {ir.planner_constraints.map((constraint) => (
              <Badge key={`${constraint.name}-${constraint.value}`} variant="neutral">
                {constraint.name}: {constraint.value}
                <span className="ml-1 opacity-60">({constraint.strength})</span>
              </Badge>
            ))}
          </div>
        </div>
      )}

      {ir.planner_assumptions?.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] text-subtle-foreground">Planner 假设</p>
          <ul className="mt-1.5 space-y-1">
            {ir.planner_assumptions.map((assumption) => (
              <li key={assumption} className="text-[12px] leading-5 text-muted-foreground">
                · {assumption}
              </li>
            ))}
          </ul>
        </div>
      )}

      {ir.warnings?.length > 0 && (
        <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-warning-soft px-2.5 py-2 text-[11.5px] leading-5 text-warning">
          <AlertTriangle className="mt-0.5 size-3 shrink-0" />
          警告：{ir.warnings.join("；")}
        </p>
      )}

      {ir.unsupported_constraints?.length ? (
        <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-surface-muted px-2.5 py-2 text-[11.5px] leading-5 text-muted-foreground">
          <AlertTriangle className="mt-0.5 size-3 shrink-0" />
          不支持的约束：{ir.unsupported_constraints.join("、")}（仅记录，不做硬过滤）
        </p>
      ) : null}
    </Section>
  );
}
