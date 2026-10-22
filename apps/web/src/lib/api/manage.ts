import { apiFetch, buildQuery } from "./client";
import type {
  Capabilities,
  CatalogFacets,
  CatalogStats,
  ChunkPreview,
  DocumentPage,
  FaqPage,
  JobSummary,
  LlmConfig,
  ManagedDocumentDetail,
  ManagedFaq,
} from "./types";

export interface DocumentQuery {
  q?: string;
  status?: string;
  published?: "true" | "false";
  technical_review?: string;
  domain_review?: string;
  document_type?: string;
  source_type?: string;
  authority_level?: string;
  language?: string;
  species?: string;
  category?: string;
  license?: string;
  source_id?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

export interface FaqQuery {
  q?: string;
  review_status?: string;
  evidence_status?: string;
  usage_scope?: string;
  species?: string;
  indexed?: "true" | "false";
  limit?: number;
  offset?: number;
}

interface ChunkPage {
  items: ChunkPreview[];
  total: number;
  limit: number;
  offset: number;
}

interface JobPage {
  items: JobSummary[];
  total: number;
  limit: number;
  offset: number;
}

interface DataSourceItem {
  id: string;
  url: string;
  title: string;
  publisher: string;
  authority: string;
  doc_type: string;
  language: string;
  publish_date: string | null;
  effective_date: string | null;
  species: string[];
  topics: string[];
  region: string | null;
  policy: string;
  license: string | null;
  resolver: string;
  notes: string;
  documents_active: number;
  documents_staging: number;
  chunks: number;
}

export interface DataSourcesResponse {
  total: number;
  by_authority: Record<string, number>;
  by_policy: Record<string, number>;
  items: DataSourceItem[];
}

export interface DataRun {
  id: string;
  kind: string;
  status: string;
  params: Record<string, unknown>;
  stats: Record<string, number | string | null>;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export const manageApi = {
  documents: (query: DocumentQuery) =>
    apiFetch<DocumentPage>(`/api/manage/documents${buildQuery({ ...query })}`),
  stats: () => apiFetch<CatalogStats>("/api/manage/stats"),
  facets: (includeDeleted = true) =>
    apiFetch<CatalogFacets>(`/api/manage/facets${buildQuery({ include_deleted: includeDeleted })}`),
  document: (documentId: string) =>
    apiFetch<ManagedDocumentDetail>(`/api/manage/documents/${documentId}`),
  chunks: (
    documentId: string,
    query: { version_id?: string; role?: string; page?: number; q?: string; limit?: number; offset?: number },
  ) => apiFetch<ChunkPage>(`/api/manage/documents/${documentId}/chunks${buildQuery({ ...query })}`),
  jobs: (query: { status?: string; kind?: string; document_id?: string; limit?: number; offset?: number } = {}) =>
    apiFetch<JobPage>(`/api/manage/jobs${buildQuery({ ...query })}`),
  faq: (query: FaqQuery = {}) => apiFetch<FaqPage>(`/api/manage/faq${buildQuery({ ...query })}`),
  faqDetail: (faqId: string) => apiFetch<ManagedFaq>(`/api/manage/faq/${faqId}`),
  faqStats: () =>
    apiFetch<{
      total: number;
      pending: number;
      verified: number;
      rejected: number;
      by_status: Record<string, number>;
      by_scope: Record<string, number>;
      verified_indexed: number;
      index_points: number | null;
      index_points_error: string | null;
    }>("/api/manage/faq/stats/summary"),
  capabilities: () => apiFetch<Capabilities>("/api/manage/capabilities"),
  llmConfig: () => apiFetch<LlmConfig>("/api/manage/llm"),
  updateLlmModel: (model: string, ping = true) =>
    apiFetch<LlmConfig>("/api/manage/llm", {
      method: "PUT",
      body: JSON.stringify({ model, ping }),
    }),
  dataSources: () => apiFetch<DataSourcesResponse>("/api/data/sources"),
  dataRuns: (limit = 20) => apiFetch<DataRun[]>(`/api/data/runs${buildQuery({ limit })}`),
};
