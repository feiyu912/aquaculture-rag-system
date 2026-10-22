"use client";

import { useQuery } from "@tanstack/react-query";

import { manageApi, type DocumentQuery, type FaqQuery } from "@/lib/api/manage";

export function useCatalogStats() {
  return useQuery({
    queryKey: ["manage", "stats"],
    queryFn: manageApi.stats,
    staleTime: 15_000,
  });
}

export function useCatalogFacets() {
  return useQuery({
    queryKey: ["manage", "facets"],
    queryFn: () => manageApi.facets(true),
    staleTime: 60_000,
  });
}

export function useDocumentPage(query: DocumentQuery) {
  return useQuery({
    queryKey: ["manage", "documents", query],
    queryFn: () => manageApi.documents(query),
    staleTime: 10_000,
  });
}

export function useManagedDocument(documentId: string | null) {
  return useQuery({
    queryKey: ["manage", "document", documentId],
    queryFn: () => manageApi.document(documentId as string),
    enabled: Boolean(documentId),
    retry: false,
  });
}

export function useDocumentChunks(
  documentId: string | null,
  query: { version_id?: string; role?: string; page?: number; q?: string; limit?: number; offset?: number },
) {
  return useQuery({
    queryKey: ["manage", "chunks", documentId, query],
    queryFn: () => manageApi.chunks(documentId as string, query),
    enabled: Boolean(documentId),
  });
}

export function useJobs(query: { status?: string; kind?: string; limit?: number; offset?: number } = {}) {
  return useQuery({
    queryKey: ["manage", "jobs", query],
    queryFn: () => manageApi.jobs(query),
    staleTime: 10_000,
  });
}

export function useFaqPage(query: FaqQuery) {
  return useQuery({
    queryKey: ["manage", "faq", query],
    queryFn: () => manageApi.faq(query),
    staleTime: 10_000,
  });
}

export function useFaqDetail(faqId: string | null) {
  return useQuery({
    queryKey: ["manage", "faq-detail", faqId],
    queryFn: () => manageApi.faqDetail(faqId as string),
    enabled: Boolean(faqId),
    retry: false,
  });
}

export function useFaqStats() {
  return useQuery({
    queryKey: ["manage", "faq-stats"],
    queryFn: manageApi.faqStats,
    staleTime: 15_000,
  });
}

export function useCapabilities() {
  return useQuery({
    queryKey: ["capabilities"],
    queryFn: manageApi.capabilities,
    staleTime: 60_000,
  });
}

export function useLlmConfig() {
  return useQuery({
    queryKey: ["llm-config"],
    queryFn: manageApi.llmConfig,
    staleTime: 30_000,
  });
}
