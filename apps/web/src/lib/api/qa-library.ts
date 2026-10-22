import { apiFetch, buildQuery } from "./client";

export interface QaLibraryItem {
  original_id: string;
  question: string;
  answer: string;
  topics: string[];
  species: string[];
  dataset_id: string;
  license: string | null;
  score?: number;
}

export interface QaLibraryPage {
  items: QaLibraryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface QaLibrarySummary {
  available: boolean;
  total: number;
  datasets: { dataset_id: string; count: number }[];
  topics: { topic: string; count: number }[];
}

export interface QaLibraryQuery {
  q?: string;
  topic?: string;
  limit?: number;
  offset?: number;
}

export const DATASET_LABELS: Record<string, string> = {
  "Mxode/Chinese-QA-Agriculture_Forestry_Animal_Husbandry_Fishery": "中文农林牧渔问答",
  "KurmaAI/AQUA-Test-Dataset": "英文水产问答",
};

export function datasetLabel(datasetId: string): string {
  return DATASET_LABELS[datasetId] ?? datasetId;
}

export const qaLibraryApi = {
  summary: () => apiFetch<QaLibrarySummary>("/api/qa-library/summary"),
  list: (query: QaLibraryQuery = {}) =>
    apiFetch<QaLibraryPage>(`/api/qa-library${buildQuery({ ...query })}`),
};