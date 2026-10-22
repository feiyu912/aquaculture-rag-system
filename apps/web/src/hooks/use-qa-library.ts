"use client";

import { useQuery } from "@tanstack/react-query";

import { qaLibraryApi, type QaLibraryQuery } from "@/lib/api/qa-library";

export function useQaLibrarySummary() {
  return useQuery({
    queryKey: ["qa-library", "summary"],
    queryFn: qaLibraryApi.summary,
    staleTime: 60_000,
  });
}

export function useQaLibraryPage(query: QaLibraryQuery, enabled = true) {
  return useQuery({
    queryKey: ["qa-library", "list", query],
    queryFn: () => qaLibraryApi.list(query),
    staleTime: 10_000,
    enabled,
  });
}