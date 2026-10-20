"use client";

import * as React from "react";
import { Anchor, Info } from "lucide-react";

import { Section } from "@/components/debug/section";
import { Badge } from "@/components/ui/badge";
import type { SourceAwareTrace } from "@/lib/api/debug-types";
import type { QueryTrace } from "@/lib/api/types";

/**
 * Per-source evidence anchoring.
 *
 * Only fires when the question explicitly names two or more standards; the
 * backend records why it did or did not activate, and this panel shows that
 * verbatim rather than inventing a state.
 */
export function SourceAwareCard({ trace }: { trace: QueryTrace }) {
  const aware = (trace.source_aware_retrieval ??
    trace.retrieval_config?.source_aware_retrieval) as SourceAwareTrace | null | undefined;

  if (!aware) {
    return (
      <Section title="按来源锚定检索" hint="多标准对比问题">
        <p className="text-[12.5px] text-muted-foreground">
          本次请求没有记录来源锚定信息。
        </p>
      </Section>
    );
  }

  // The backend may report only `{"enabled": true}` when the anchor stage
  // produced no detailed trace; never invent the missing values.
  const detailed = Array.isArray(aware.cited);
  const citedCodes = detailed ? aware.cited.map((anchor) => anchor.code) : [];
  const resolvedCodes = detailed ? Object.keys(aware.resolved ?? {}) : [];

  return (
    <Section
      title="按来源锚定检索"
      hint="问题显式引用两个及以上标准时生效"
      action={
        <Badge variant={aware.active ? "success" : "neutral"} className="gap-1">
          <Anchor className="size-3" />
          {aware.active ? "已生效" : detailed ? "未生效" : "已启用"}
        </Badge>
      }
    >
      {detailed ? (
        <>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12.5px]">
            <div className="min-w-0">
              <dt className="text-[11px] text-subtle-foreground">问题中引用的标准</dt>
              <dd className="mt-0.5 truncate font-medium text-foreground">
                {citedCodes.length ? citedCodes.join("、") : "—"}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-[11px] text-subtle-foreground">已解析到文档</dt>
              <dd className="mt-0.5 truncate font-medium text-foreground">
                {resolvedCodes.length ? resolvedCodes.join("、") : "—"}
              </dd>
            </div>
          </dl>

          {aware.reason && (
            <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-surface-muted px-2.5 py-2 text-[11.5px] leading-5 text-muted-foreground">
              <Info className="mt-0.5 size-3 shrink-0" />
              未生效原因：<code className="font-mono">{aware.reason}</code>
            </p>
          )}

          {aware.active && (
            <p className="mt-3 rounded-lg bg-success-soft px-2.5 py-2 text-[11.5px] leading-5 text-success">
              为每个被引用的标准预留了独立证据位，避免长文档把另一个来源挤出证据窗口。
            </p>
          )}
        </>
      ) : (
        <p className="text-[12.5px] text-muted-foreground">
          服务端本次只报告了锚定功能已开启，没有记录被引用的标准明细。
        </p>
      )}
    </Section>
  );
}
