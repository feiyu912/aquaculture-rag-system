"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock,
  RotateCcw,
  Waves,
} from "lucide-react";

import { AnswerMarkdown } from "@/components/chat/answer-markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ChatMessage as ChatMessageType } from "@/components/chat/types";
import { formatMs, formatPercent } from "@/lib/utils";
import { cn } from "@/lib/utils";

const MODE_LABEL: Record<string, string> = {
  dense: "Dense",
  bm25: "BM25",
  hybrid: "Hybrid + RRF",
  hybrid_rerank: "Hybrid + Rerank",
};

function UserMessage({ message }: { message: ChatMessageType }) {
  return (
    <article className="flex justify-end">
      <div className="max-w-[min(560px,86%)]">
        <div className="mb-1 flex items-center justify-end gap-2 text-[11px] text-subtle-foreground">
          <span>你</span>
        </div>
        <div className="rounded-2xl rounded-br-md bg-primary-btn px-4 py-2.5 text-[14.5px] leading-[1.7] text-primary-fg shadow-sm">
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        </div>
      </div>
    </article>
  );
}

function MetaStrip({ message }: { message: ChatMessageType }) {
  const meta = message.meta;
  const report = message.citationCheck;
  const timings = meta?.timings;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border/70 pt-2.5 text-[11.5px] text-subtle-foreground">
      {meta?.model && (
        <span className="font-medium text-muted-foreground">{meta.model}</span>
      )}
      {meta?.retrievalMode && (
        <span>{MODE_LABEL[meta.retrievalMode] ?? meta.retrievalMode}</span>
      )}
      {timings?.ttft_ms != null && (
        <span className="inline-flex items-center gap-1">
          <Clock className="size-3" />
          首字 {formatMs(timings.ttft_ms)}
        </span>
      )}
      {timings?.total_ms != null && <span>总计 {formatMs(timings.total_ms)}</span>}
      {report && (
        <span
          className={cn(
            "inline-flex items-center gap-1",
            report.valid ? "text-success" : "text-danger",
          )}
        >
          {report.valid ? (
            <CheckCircle2 className="size-3" />
          ) : (
            <CircleAlert className="size-3" />
          )}
          引用{report.valid ? "有效" : "含无效编号"}
          {report.factual_sentences > 0 && (
            <span className="text-subtle-foreground">
              （覆盖 {formatPercent(report.coverage)}）
            </span>
          )}
        </span>
      )}
      {message.requestId && (
        <Link
          href={`/debug?request_id=${encodeURIComponent(message.requestId)}`}
          className="inline-flex items-center gap-1 text-primary-600 transition-colors hover:text-primary-700 hover:underline"
        >
          检索详情
        </Link>
      )}
    </div>
  );
}

function AssistantMessage({
  message,
  activeSourceIndex,
  onCitationSelect,
  onRetry,
  onShowSources,
}: {
  message: ChatMessageType;
  activeSourceIndex: number | null;
  onCitationSelect: (messageId: string, index: number) => void;
  onRetry: (messageId: string) => void;
  onShowSources: (messageId: string) => void;
}) {
  const sources = message.sources ?? [];
  const insufficient = message.meta?.sufficient === false && sources.length === 0;
  const isStreaming = message.status === "streaming";

  return (
    <article className="group flex gap-3">
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-500 to-primary-800 text-white shadow-sm">
        <Waves className="size-4" strokeWidth={2.1} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-semibold text-foreground">Aqua 助手</span>
          {message.meta?.retrievalMode && (
            <Badge variant="neutral" className="font-normal">
              {MODE_LABEL[message.meta.retrievalMode] ?? message.meta.retrievalMode}
            </Badge>
          )}
          {isStreaming && (
            <span className="inline-flex items-center gap-1.5 text-[11.5px] text-primary-600">
              <span className="relative flex size-1.5">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary-400 opacity-75" />
                <span className="relative inline-flex size-1.5 rounded-full bg-primary-600" />
              </span>
              生成中
            </span>
          )}
        </div>

        {insufficient ? (
          <div className="rounded-xl border border-warning/25 bg-warning-soft px-3.5 py-3">
            <div className="flex items-start gap-2.5">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
              <div className="min-w-0">
                <p className="text-[13px] font-semibold text-foreground">证据不足，无法作答</p>
                <p className="mt-1 text-[12.5px] leading-5 text-muted-foreground">
                  知识库中没有检索到与该问题匹配的可靠资料，系统已拒绝生成事实性结论。
                  {message.meta?.gate?.reason && (
                    <span className="ml-1 text-subtle-foreground">
                      原因码：
                      <code className="rounded bg-surface px-1 py-0.5 font-mono text-[11px]">
                        {message.meta.gate.reason}
                      </code>
                    </span>
                  )}
                </p>
              </div>
            </div>
          </div>
        ) : message.content ? (
          <AnswerMarkdown
            content={message.content}
            availableIndices={sources.map((source) => source.index)}
            activeIndex={activeSourceIndex}
            onCitationSelect={(index) => onCitationSelect(message.id, index)}
          />
        ) : isStreaming ? (
          <div className="flex items-center gap-2 py-1 text-[13px] text-subtle-foreground">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-subtle-foreground [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-subtle-foreground [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-subtle-foreground" />
            <span className="ml-1">正在检索并生成回答…</span>
          </div>
        ) : (
          <p className="text-[13px] text-subtle-foreground">（本次回答没有返回内容）</p>
        )}

        {message.status === "failed" && message.error && (
          <div className="mt-2 flex items-start gap-2.5 rounded-xl border border-danger/25 bg-danger-soft px-3.5 py-3">
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger" />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold text-foreground">生成失败</p>
              <p className="mt-0.5 text-[12.5px] leading-5 text-muted-foreground">
                {message.error.message}
              </p>
            </div>
            {message.error.retryable && (
              <Button variant="outline" size="xs" onClick={() => onRetry(message.id)}>
                <RotateCcw className="size-3" />
                重试
              </Button>
            )}
          </div>
        )}

        {message.status === "interrupted" && (
          <div className="mt-2 flex items-start gap-2.5 rounded-xl border border-warning/25 bg-warning-soft px-3.5 py-3">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold text-foreground">
                {message.error?.message?.startsWith("已停止")
                  ? "已停止生成"
                  : "回答未完成"}
              </p>
              <p className="mt-0.5 text-[12.5px] leading-5 text-muted-foreground">
                {message.error?.message ??
                  "生成过程中连接被中断，没有留下任何内容。"}
              </p>
            </div>
            <Button variant="outline" size="xs" onClick={() => onRetry(message.id)}>
              <RotateCcw className="size-3" />
              重试
            </Button>
          </div>
        )}

        {sources.length > 0 && (
          <button
            type="button"
            onClick={() => onShowSources(message.id)}
            className="mt-2.5 inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-muted px-2.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground"
          >
            <span className="tabular">{sources.length}</span> 个引用来源
            <ChevronDown className="size-3" />
          </button>
        )}

        {message.status === "completed" && <MetaStrip message={message} />}
      </div>
    </article>
  );
}

export function MessageList({
  messages,
  activeMessageId,
  activeSourceIndex,
  onCitationSelect,
  onRetry,
  onShowSources,
  bottomRef,
}: {
  messages: ChatMessageType[];
  activeMessageId: string | null;
  activeSourceIndex: number | null;
  onCitationSelect: (messageId: string, index: number) => void;
  onRetry: (messageId: string) => void;
  onShowSources: (messageId: string) => void;
  bottomRef?: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="flex flex-col gap-7">
      {messages.map((message) =>
        message.role === "user" ? (
          <UserMessage key={message.id} message={message} />
        ) : (
          <AssistantMessage
            key={message.id}
            message={message}
            activeSourceIndex={message.id === activeMessageId ? activeSourceIndex : null}
            onCitationSelect={onCitationSelect}
            onRetry={onRetry}
            onShowSources={onShowSources}
          />
        ),
      )}
      <div ref={bottomRef} />
    </div>
  );
}
