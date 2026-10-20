"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { ChatEmptyState, ChatToolbar } from "@/components/chat/chat-empty-state";
import { Composer } from "@/components/chat/composer";
import { MessageList } from "@/components/chat/message-list";
import { SourcePanel } from "@/components/chat/source-panel";
import { SourcePanelDrawer } from "@/components/chat/source-panel-drawer";
import { Skeleton } from "@/components/ui/skeleton";
import { documentsApi } from "@/lib/api/documents";
import type { RetrievalMode, Source } from "@/lib/api/types";
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
  const panelDismissedRef = React.useRef(false);

  const { data: speciesOptions } = useQuery({
    queryKey: ["species"],
    queryFn: documentsApi.species,
    staleTime: 60_000,
  });

  const { data: documents } = useQuery({
    queryKey: ["documents"],
    queryFn: documentsApi.list,
    staleTime: 30_000,
  });

  const scrollRef = React.useRef<HTMLDivElement>(null);
  const bottomRef = React.useRef<HTMLDivElement>(null);
  const stickToBottomRef = React.useRef(true);

  const activeSources: Source[] = React.useMemo(() => {
    const withSources = chat.messages.filter(
      (message) => message.role === "assistant" && (message.sources?.length ?? 0) > 0,
    );
    const last = withSources[withSources.length - 1];
    return last?.sources ?? [];
  }, [chat.messages]);

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

  const handleSelectSource = (index: number) => {
    setActiveSourceIndex(index);
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

  const handleOpenPdf = (source: Source) => {
    const params = new URLSearchParams({
      document_id: source.document_id,
      version_id: source.version_id,
    });
    if (source.page) params.set("page", String(source.page));
    // Carry the canonical bbox so the reader can highlight the exact region
    // that was quoted, not just the page.
    if (source.location?.bbox) {
      params.set("bbox", source.location.bbox.map((value) => value.toFixed(2)).join(","));
    }
    router.push(`/reader?${params.toString()}`);
  };

  const handleSend = () => {
    const question = draft.trim();
    if (!question) return;
    setDraft("");
    void chat.send(question);
  };

  const hasDocuments = (documents?.length ?? 0) > 0;

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
                activeSourceIndex={activeSourceIndex}
                onCitationSelect={handleSelectSource}
                onRetry={(messageId) => void chat.retry(messageId)}
                onShowSources={() => setPanelOpen(true)}
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
            onSelect={handleSelectSource}
            onOpenPdf={handleOpenPdf}
            onClose={() => setPanelOpen(false)}
          />
          <SourcePanelDrawer
            open={panelOpen}
            sources={activeSources}
            selectedIndex={activeSourceIndex}
            onSelect={handleSelectSource}
            onOpenPdf={handleOpenPdf}
            onClose={() => setPanelOpen(false)}
          />
        </>
      )}
    </div>
  );
}
