"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { sessionsApi } from "@/lib/api/chat";
import type { SessionOut } from "@/lib/api/types";

export function useSessions() {
  return useQuery<SessionOut[]>({
    queryKey: ["sessions"],
    queryFn: sessionsApi.list,
  });
}

export function useDeleteSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => sessionsApi.remove(sessionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}
