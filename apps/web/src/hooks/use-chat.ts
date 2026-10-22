"use client";

import * as React from "react";

import { ApiError } from "@/lib/api/client";
import { sessionsApi, streamChat } from "@/lib/api/chat";
import type { CitationOut, RetrievalMode, Source } from "@/lib/api/types";
import type { ChatMessage, ChatStatusState } from "@/components/chat/types";

const LAST_SESSION_KEY = "aqua-rag:last-session";

function citationToSource(citation: CitationOut): Source {
  const sourceType = citation.source_type ?? "document";
  return {
    source_id: `S${citation.source_index}`,
    index: citation.source_index,
    source_type: sourceType,
    media_type:
      citation.media_type ?? (sourceType === "faq" ? "faq" : citation.page ? "pdf" : "pdf"),
    document_id: citation.document_id,
    version_id: citation.document_version_id,
    version_no: citation.version_no ?? 0,
    title: citation.title ?? "已删除文档",
    species: citation.species ?? [],
    page: citation.page,
    page_end: citation.page_end ?? citation.page,
    quote: citation.quote,
    heading_path: [],
    // `location` is canonical; `bbox` keeps older rows working.
    location: citation.location ?? citation.bbox ?? null,
    locations: citation.locations ?? [],
    faq_id: citation.faq_id ?? null,
    source_url: citation.source_url ?? null,
    available: citation.available ?? true,
    unavailable_reason: citation.unavailable_reason ?? null,
  };
}

let localIdCounter = 0;
function localId(prefix: string) {
  localIdCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${localIdCounter}`;
}

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export interface UseChatOptions {
  retrievalMode: RetrievalMode;
  species: string | null;
}

export function useChat(options: UseChatOptions) {
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState<ChatStatusState | null>(null);
  const [isStreaming, setIsStreaming] = React.useState(false);
  const [historyLoading, setHistoryLoading] = React.useState(false);
  const [activeMessageId, setActiveMessageId] = React.useState<string | null>(null);

  const abortRef = React.useRef<AbortController | null>(null);
  const optionsRef = React.useRef(options);
  optionsRef.current = options;

  const stop = React.useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const loadSession = React.useCallback(async (targetSessionId: string) => {
    setHistoryLoading(true);
    try {
      const history = await sessionsApi.messages(targetSessionId);
      const mapped: ChatMessage[] = history.map((message) => {
        // A message left in `streaming` was interrupted (the backend restarted
        // mid-answer). Surface it as incomplete instead of an empty bubble.
        const interrupted = message.status === "streaming";
        const failed = message.status === "failed";
        return {
          id: message.id,
          backendId: message.id,
          role: message.role === "assistant" ? "assistant" : "user",
          content: message.content,
          status: interrupted ? "interrupted" : failed ? "failed" : "completed",
          createdAt: message.created_at,
          sources: message.citations.map(citationToSource),
          citationCheck: (message.meta?.citation_check as ChatMessage["citationCheck"]) ?? undefined,
          error: failed
            ? {
                message:
                  (message.meta?.error as string | undefined) ??
                  "上一次回答没有完成，请重试。",
                retryable: true,
              }
            : undefined,
          meta: {
            model: message.model ?? undefined,
            timings: message.latency_ms ? { total_ms: message.latency_ms } : undefined,
          },
        } as ChatMessage;
      });
      setMessages(mapped);
      setSessionId(targetSessionId);
      window.localStorage.setItem(LAST_SESSION_KEY, targetSessionId);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const resetSession = React.useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setSessionId(null);
    setStatus(null);
    setActiveMessageId(null);
    window.localStorage.removeItem(LAST_SESSION_KEY);
  }, []);

  const send = React.useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || isStreaming) return;

      const userMessage: ChatMessage = {
        id: localId("user"),
        role: "user",
        content: trimmed,
        status: "completed",
        createdAt: new Date().toISOString(),
      };
      const assistantId = localId("assistant");
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        status: "streaming",
        createdAt: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setActiveMessageId(assistantId);
      setIsStreaming(true);
      setStatus({ stage: "querying", sources: 0, sufficient: true });

      const controller = new AbortController();
      abortRef.current = controller;

      const patchAssistant = (patch: Partial<ChatMessage>) => {
        setMessages((prev) =>
          prev.map((message) =>
            message.id === assistantId ? { ...message, ...patch } : message,
          ),
        );
      };

      try {
        await streamChat(
          {
            question: trimmed,
            session_id: sessionId,
            retrieval_mode: optionsRef.current.retrievalMode,
            species: optionsRef.current.species,
          },
          {
            onMeta: (payload) => {
              setSessionId(payload.session_id);
              window.localStorage.setItem(LAST_SESSION_KEY, payload.session_id);
              patchAssistant({ backendId: payload.message_id, requestId: payload.request_id });
            },
            onStatus: (payload) => {
              setStatus({
                stage: payload.stage,
                sources: payload.sources,
                sufficient: payload.sufficient,
                retrievalMode: payload.retrieval_mode,
                gate: payload.gate,
                queryIr: payload.query_ir,
                llmPlanner: payload.llm_planner ?? null,
              });
              patchAssistant({
                meta: {
                  ...(assistantMessage.meta ?? {}),
                  retrievalMode: payload.retrieval_mode,
                  sufficient: payload.sufficient,
                  gate: payload.gate,
                  queryIr: payload.query_ir,
                },
              });
            },
            onSources: (sources: Source[]) => {
              patchAssistant({ sources });
              setStatus((prev) => (prev ? { ...prev, sources: sources.length } : prev));
            },
            onToken: (text) => {
              setMessages((prev) =>
                prev.map((message) =>
                  message.id === assistantId
                    ? { ...message, content: message.content + text }
                    : message,
                ),
              );
            },
            onCitationCheck: (report) => {
              patchAssistant({ citationCheck: report });
            },
            onDone: (payload) => {
              patchAssistant({
                status: "completed",
                backendId: payload.message_id,
                meta: {
                  model: payload.model,
                  timings: payload.timings,
                  retrievalMode: payload.retrieval_mode,
                  sufficient: payload.sufficient,
                  gate: payload.gate,
                  queryIr: payload.query_ir,
                  costUsd: payload.cost_usd,
                  usage: payload.usage,
                },
              });
            },
            onServerError: (payload) => {
              patchAssistant({
                status: "failed",
                error: { message: payload.message, retryable: payload.retryable },
              });
            },
          },
          controller.signal,
        );

        // The stream ended without a `done` frame — treat as an interruption.
        setMessages((prev) =>
          prev.map((message) =>
            message.id === assistantId && message.status === "streaming"
              ? {
                  ...message,
                  status: "failed",
                  error: { message: "连接已中断，回答可能不完整。", retryable: true },
                }
              : message,
          ),
        );
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          // The user pressed "停止": keep whatever was generated and say so.
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantId
                ? {
                    ...message,
                    status: "interrupted",
                    error: {
                      message: message.content
                        ? "已停止生成，以上是已产生的部分内容。"
                        : "已停止生成。",
                      retryable: true,
                    },
                  }
                : message,
            ),
          );
        } else {
          const message =
            error instanceof ApiError ? error.message : "请求失败，请稍后重试。";
          const retryable = error instanceof ApiError ? error.retryable : true;
          patchAssistant({ status: "failed", error: { message, retryable } });
        }
      } finally {
        abortRef.current = null;
        setIsStreaming(false);
        setStatus(null);
      }
    },
    [isStreaming, sessionId],
  );

  const retry = React.useCallback(
    async (messageId: string) => {
      const index = messages.findIndex((message) => message.id === messageId);
      if (index <= 0) return;
      const question = messages[index - 1];
      if (question.role !== "user") return;
      setMessages((prev) => prev.filter((message) => message.id !== messageId));
      await send(question.content);
    },
    [messages, send],
  );

  // Restore a session on first mount. A `?session_id=` query wins so a
  // conversation can be linked to directly; otherwise the last session used
  // in this browser is restored.
  const restoredRef = React.useRef(false);
  React.useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;

    const requested = new URLSearchParams(window.location.search).get("session_id");
    if (requested) {
      if (!UUID_RE.test(requested)) {
        window.localStorage.removeItem(LAST_SESSION_KEY);
        return;
      }
      loadSession(requested).catch(() => {
        window.localStorage.removeItem(LAST_SESSION_KEY);
        setMessages([]);
        setSessionId(null);
      });
      return;
    }

    const stored = window.localStorage.getItem(LAST_SESSION_KEY);
    if (!stored) return;
    loadSession(stored).catch(() => {
      window.localStorage.removeItem(LAST_SESSION_KEY);
    });
  }, [loadSession]);

  return {
    messages,
    sessionId,
    status,
    isStreaming,
    historyLoading,
    activeMessageId,
    setActiveMessageId,
    send,
    stop,
    retry,
    loadSession,
    resetSession,
  };
}
