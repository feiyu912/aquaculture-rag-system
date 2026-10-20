"use client";

import * as React from "react";

import { AppShell } from "@/components/layout/app-shell";
import { ChatWorkspace } from "@/components/chat/chat-workspace";
import { SessionSidebar } from "@/components/chat/session-sidebar";
import { useChat } from "@/hooks/use-chat";
import type { RetrievalMode } from "@/lib/api/types";

export default function ChatPage() {
  const [retrievalMode, setRetrievalMode] = React.useState<RetrievalMode>("hybrid");
  const [species, setSpecies] = React.useState<string | null>(null);

  const chat = useChat({ retrievalMode, species });

  return (
    <AppShell
      contextLabel="会话"
      context={
        <SessionSidebar
          activeSessionId={chat.sessionId}
          onSelect={(sessionId) => void chat.loadSession(sessionId)}
          onCreate={chat.resetSession}
        />
      }
    >
      <ChatWorkspace
        chat={chat}
        retrievalMode={retrievalMode}
        onRetrievalModeChange={setRetrievalMode}
        species={species}
        onSpeciesChange={setSpecies}
      />
    </AppShell>
  );
}
