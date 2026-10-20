"use client";

import { useQuery } from "@tanstack/react-query";

import { healthApi } from "@/lib/api/documents";
import type { HealthResponse } from "@/lib/api/types";

export function useHealth() {
  return useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: healthApi.get,
    refetchInterval: 20_000,
    staleTime: 10_000,
  });
}
