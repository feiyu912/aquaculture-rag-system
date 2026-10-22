"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { ChatEmptyState, ChatToolbar } from "@/components/chat/chat-empty-state";
import { Composer } from "@/components/chat/composer";
import { MessageList } from "@/components/chat/message-list";
import { SourcePanel } from "@/components/chat/source-panel";
import { SourcePanelDrawer } from "@/components/chat/source-panel-drawer";
import { Skeleton } from "@/components/ui/skeleton";
import { documentsApi } from "@/lib/api/documents";
import type { RetrievalMode, Source } from "@/lib/api/types";
import { useCatalogStats } from "@/hooks/use-management";
import { unavailableReasonLabel } from "@/lib/labels";
import type { useChat } from "@/hooks/use-chat";

type ChatController = ReturnType<typeof useChat>;

export function ChatWorkspace({
  chat,
  retrievalMode,
  onRetrievalModeChange,
  species,
  onSpeciesChange,
}: {
  chat: ChatController;
  retrievalMode: RetrievalMode;
  onRetrievalModeChange: (mode: RetrievalMode) => void;
  species: string | null;
  onSpeciesChange: (value: string | null) => void;
}) {
  const router = useRouter();
  const [draft, setDraft] = React.useState("");
  const [panelOpen, setPanelOpen] = React.useState(false);
  const [activeSourceIndex, setActiveSourceIndex] = React.useState<number | null>(null);
  const [activeMessageId, setActiveMessageId] = React.useState<string | null>(null);
  const panelDismissedRef = React.useRef(false);

  const { data: speciesOptions } = useQuery({
    queryKey: ["species"],
    queryFn: documentsApi.species,
    staleTime: 60_000,
  });

  const { data: catalogStats } = useCatalogStats();

  const scrollRef = React.useRef<HTMLDivElement>(null);
  const bottomRef = React.useRef<HTMLDivElement>(null);
  const stickToBottomRef = React.useRef(true);

  const latestWithSources = React.useMemo(() => {
    const withSources = chat.messages.filter(
      (message) => message.role === "assistant" && (message.sources?.length ?? 0) > 0,
    );
    return withSources[withSources.length - 1] ?? null;
  }, [chat.messages]);

  // Follow the newest answer by default. Selecting a citation in an older
  // answer pins that message, so S1 always opens that message's own S1 — not
  // the same index in the newest answer.
  const lastSeenLatestRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (latestWithSources && latestWithSources.id !== lastSeenLatestRef.current) {
      lastSeenLatestRef.current = latestWithSources.id;
      setActiveMessageId(latestWithSources.id);
      setActiveSourceIndex(null);
    }
  }, [latestWithSources]);

  const activeMessage = React.useMemo(
    () => chat.messages.find((message) => message.id === activeMessageId) ?? null,
    [chat.messages, activeMessageId],
  );
  const activeSources: Source[] = activeMessage?.sources ?? [];

  const handleScroll = () => {
    const node = scrollRef.current;
    if (!node) return;
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    stickToBottomRef.current = distance < 120;
  };

  React.useEffect(() => {
    if (!stickToBottomRef.current) return;
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [chat.messages, chat.status]);

  const handleSelectSource = (messageId: string, index: number) => {
    setActiveMessageId(messageId);
    setActiveSourceIndex(index);
    setPanelOpen(true);
  };

  const handleShowSources = (messageId: string) => {
    setActiveMessageId(messageId);
    setActiveSourceIndex(null);
    setPanelOpen(true);
  };

  // Reveal the citation panel the first time real sources arrive, unless the
  // user explicitly dismissed it. On narrow viewports the panel is an
  // overlay, so we leave it closed and let the user open it deliberately.
  const hadSourcesRef = React.useRef(false);
  React.useEffect(() => {
    if (activeSources.length === 0) {
      hadSourcesRef.current = false;
      return;
    }
    if (!hadSourcesRef.current && !panelDismissedRef.current) {
      if (window.matchMedia("(min-width: 1280px)").matches) {
        setPanelOpen(true);
      }
    }
    hadSourcesRef.current = true;
  }, [activeSources.length]);

  const togglePanel = React.useCallback(() => {
    setPanelOpen((prev) => {
      if (prev) panelDismissedRef.current = true;
      return !prev;
    });
  }, []);

  const handleOpenSource = (source: Source) => {
    if (source.available === false) {
      toast.error("来源不可访问", {
        description: unavailableReasonLabel(source.unavailable_reason),
      });
      return;
    }
    if (source.media_type === "faq") {
      if (!source.faq_id) {
        toast.error("FAQ 引用缺少条目标识，无法打开");
        return;
      }
      router.push(`/source?faq_id=${encodeURIComponent(source.faq_id)}`);
      return;
    }
    if (!source.document_id) {
      toast.error("引用缺少文档标识，无法打开原文");
      return;
    }
    if (source.media_type === "html") {
      const params = new URLSearchParams({ document_id: source.document_id });
      if (source.version_id) params.set("version_id", source.version_id);
      if (source.page) params.set("page", String(source.page));
      router.push(`/source?${params.toString()}`);
      return;
    }
    if (!source.version_id) {
      toast.error("引用的 PDF 版本已不存在", {
        description: "为避免把旧定位套到新版本，已阻止打开。",
      });
      return;
    }
    const params = new URLSearchParams({
      document_id: source.document_id,
      version_id: source.version_id,
    });
    if (source.page) params.set("page", String(source.page));
    // Carry the canonical bbox so the reader can highlight the exact region
    // that was quoted, not just the page.
    const bbox = source.location?.bbox;
    if (bbox) {
      params.set("bbox", bbox.map((value) => value.toFixed(2)).join(","));
    }
    const locations = (source.locations ?? []).filter(
      (entry) =>
        typeof entry.page === "number" &&
        Array.isArray(entry.bbox) &&
        entry.bbox.length === 4,
    );
    if (locations.length > 1) {
      params.set(
        "loc",
        JSON.stringify(
          locations.map((entry) => ({
            page: entry.page,
            bbox: entry.bbox,
          })),
        ),
      );
    }
    router.push(`/reader?${params.toString()}`);
  };

  const handleSend = () => {
    const question = draft.trim();
    if (!question) return;
    setDraft("");
    void chat.send(question);
  };

  const hasDocuments = (catalogStats?.documents.published ?? 0) > 0;

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <ChatToolbar
          status={chat.status}
          retrievalMode={retrievalMode}
          onRetrievalModeChange={onRetrievalModeChange}
          sourceCount={activeSources.length}
          panelOpen={panelOpen}
          onTogglePanel={togglePanel}
        />

        <div ref={scrollRef} onScroll={handleScroll} className="scroll-contain min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[780px] px-4 py-6 sm:px-6 sm:py-8">
            {chat.historyLoading ? (
              <div className="space-y-6">
                <Skeleton className="h-12 w-2/3" />
                <Skeleton className="h-28 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            ) : chat.messages.length === 0 ? (
              <ChatEmptyState
                hasDocuments={hasDocuments}
                onPick={(question) => {
                  setDraft(question);
                  window.setTimeout(() => {
                    document
                      .querySelector<HTMLTextAreaElement>("textarea[aria-label='输入问题']")
                      ?.focus();
                  }, 0);
                }}
              />
            ) : (
              <MessageList
                messages={chat.messages}
                activeMessageId={activeMessageId}
                activeSourceIndex={activeSourceIndex}
                onCitationSelect={handleSelectSource}
                onRetry={(messageId) => void chat.retry(messageId)}
                onShowSources={handleShowSources}
                bottomRef={bottomRef}
              />
            )}
          </div>
        </div>

        <Composer
          value={draft}
          onChange={setDraft}
          species={species}
          onSpeciesChange={onSpeciesChange}
          speciesOptions={(speciesOptions ?? []).filter((item) => item !== "通用")}
          isStreaming={chat.isStreaming}
          onSend={handleSend}
          onStop={chat.stop}
        />
      </div>

      {panelOpen && (
        <>
          <SourcePanel
            className="hidden xl:flex"
            sources={activeSources}
            selectedIndex={activeSourceIndex}
            onSelect={(index) => {
              if (activeMessageId) handleSelectSource(activeMessageId, index);
            }}
            onOpenSource={handleOpenSource}
            onClose={() => setPanelOpen(false)}
          />
          <SourcePanelDrawer
            open={panelOpen}
            sources={activeSources}
            selectedIndex={activeSourceIndex}
            onSelect={(index) => {
              if (activeMessageId) handleSelectSource(activeMessageId, index);
            }}
            onOpenSource={handleOpenSource}
            onClose={() => setPanelOpen(false)}
          />
        </>
      )}
    </div>
  );
}
