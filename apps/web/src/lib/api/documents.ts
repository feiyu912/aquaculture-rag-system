import { apiFetch } from "./client";
import type {
  DocumentDetail,
  DocumentOut,
  JobOut,
  QueryTrace,
  UploadResponse,
} from "./types";

export const healthApi = {
  get: () => apiFetch<import("./types").HealthResponse>("/api/health"),
};

export const documentsApi = {
  list: () => apiFetch<DocumentOut[]>("/api/documents"),
  detail: (documentId: string) => apiFetch<DocumentDetail>(`/api/documents/${documentId}`),
  species: () => apiFetch<string[]>("/api/species"),
  remove: (documentId: string) =>
    apiFetch<void>(`/api/documents/${documentId}`, { method: "DELETE" }),
  upload: (form: FormData) =>
    apiFetch<UploadResponse>("/api/documents", { method: "POST", body: form }),
  addVersion: (documentId: string, form: FormData) =>
    apiFetch<UploadResponse>(`/api/documents/${documentId}/versions`, { method: "POST", body: form }),
  rollback: (documentId: string, versionId: string) =>
    apiFetch<DocumentOut>(`/api/documents/${documentId}/rollback`, {
      method: "POST",
      body: JSON.stringify({ version_id: versionId }),
    }),
  job: (jobId: string) => apiFetch<JobOut>(`/api/jobs/${jobId}`),
  retryJob: (jobId: string) =>
    apiFetch<JobOut>(`/api/jobs/${jobId}/retry`, { method: "POST", body: "{}" }),
  fileUrl: (documentId: string, versionId?: string | null) =>
    versionId
      ? `/api/documents/${documentId}/file?version_id=${versionId}`
      : `/api/documents/${documentId}/file`,
};

export const debugApi = {
  trace: (requestId: string) => apiFetch<QueryTrace>(`/api/debug/query-logs/${requestId}`),
};
