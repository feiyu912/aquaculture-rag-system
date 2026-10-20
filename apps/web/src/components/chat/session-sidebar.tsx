"use client";

import * as React from "react";
import { MessageSquareText, Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useDeleteSession, useSessions } from "@/hooks/use-sessions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { SessionOut } from "@/lib/api/types";
import { cn, formatDateTime, truncate } from "@/lib/utils";

function groupSessions(sessions: SessionOut[]) {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const startOfWeek = new Date(startOfToday);
  startOfWeek.setDate(startOfWeek.getDate() - 7);

  const groups: { label: string; items: SessionOut[] }[] = [
    { label: "今天", items: [] },
    { label: "昨天", items: [] },
    { label: "过去 7 天", items: [] },
    { label: "更早", items: [] },
  ];

  for (const session of sessions) {
    const date = new Date(session.last_message_at ?? session.created_at);
    if (date >= startOfToday) groups[0].items.push(session);
    else if (date >= startOfYesterday) groups[1].items.push(session);
    else if (date >= startOfWeek) groups[2].items.push(session);
    else groups[3].items.push(session);
  }

  return groups.filter((group) => group.items.length > 0);
}

export function SessionSidebar({
  activeSessionId,
  onSelect,
  onCreate,
}: {
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onCreate: () => void;
}) {
  const { data: sessions, isLoading } = useSessions();
  const deleteSession = useDeleteSession();
  const [query, setQuery] = React.useState("");

  const filtered = React.useMemo(() => {
    const list = sessions ?? [];
    const keyword = query.trim().toLowerCase();
    if (!keyword) return list;
    return list.filter((session) => session.title.toLowerCase().includes(keyword));
  }, [sessions, query]);

  const groups = React.useMemo(() => groupSessions(filtered), [filtered]);

  const handleDelete = async (sessionId: string, title: string) => {
    try {
      await deleteSession.mutateAsync(sessionId);
      toast.success("已删除会话", { description: truncate(title, 30) });
      if (sessionId === activeSessionId) onCreate();
    } catch {
      toast.error("删除会话失败");
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-2.5 px-3 pb-3 pt-3.5">
        <Button className="w-full justify-start gap-2" onClick={onCreate} size="sm">
          <Plus className="size-4" />
          新建对话
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索会话"
            className="h-8 pl-8 text-[12.5px]"
            aria-label="搜索会话"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {isLoading ? (
          <div className="space-y-1.5 px-1">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="px-3 py-10 text-center">
            <MessageSquareText className="mx-auto size-5 text-subtle-foreground/60" />
            <p className="mt-2 text-[12.5px] text-subtle-foreground">
              {query ? "没有匹配的会话" : "还没有会话记录"}
            </p>
          </div>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="mb-3">
              <h3 className="px-2.5 pb-1 pt-2 text-[11px] font-medium text-subtle-foreground">
                {group.label}
              </h3>
              <ul className="space-y-0.5">
                {group.items.map((session) => {
                  const active = session.id === activeSessionId;
                  return (
                    <li key={session.id}>
                      <div
                        role="button"
                        tabIndex={0}
                        onClick={() => onSelect(session.id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onSelect(session.id);
                          }
                        }}
                        className={cn(
                          "group flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] transition-colors duration-150",
                          active
                            ? "bg-primary-50 font-medium text-primary-800 dark:bg-primary-500/12 dark:text-primary-300"
                            : "text-muted-foreground hover:bg-surface-muted hover:text-foreground",
                        )}
                      >
                        <MessageSquareText
                          className={cn(
                            "size-3.5 shrink-0",
                            active ? "text-primary-600" : "text-subtle-foreground",
                          )}
                        />
                        <span className="min-w-0 flex-1 truncate">
                          {truncate(session.title, 26)}
                        </span>
                        <span className="sr-only">
                          {formatDateTime(session.last_message_at ?? session.created_at)}
                        </span>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              aria-label="删除会话"
                              className="rounded p-0.5 text-subtle-foreground opacity-0 transition-opacity hover:bg-surface-inset hover:text-danger group-hover:opacity-100 focus-visible:opacity-100"
                              onClick={(event) => {
                                event.stopPropagation();
                                void handleDelete(session.id, session.title);
                              }}
                            >
                              <Trash2 className="size-3.5" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent side="right">删除会话</TooltipContent>
                        </Tooltip>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </div>
    </div>
  );
}
