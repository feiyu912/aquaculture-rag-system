"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { documentsApi } from "@/lib/api/documents";
import type { DocumentDetail, DocumentOut, JobOut } from "@/lib/api/types";

export function useDocuments() {
  return useQuery<DocumentOut[]>({
    queryKey: ["documents"],
    queryFn: documentsApi.list,
  });
}

export function useDocumentDetail(documentId: string | null) {
  return useQuery<DocumentDetail>({
    queryKey: ["document", documentId],
    queryFn: () => documentsApi.detail(documentId as string),
    enabled: Boolean(documentId),
  });
}

/**
 * Poll an ingest job until it reaches a terminal state.
 *
 * The backend processes uploads asynchronously through ARQ, so the UI has to
 * follow the job rather than assume the document is ready when the request
 * returns.
 */
export function useJobWatcher(jobId: string | null) {
  const [job, setJob] = useState<JobOut | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const next = await documentsApi.job(jobId);
        if (cancelled) return;
        setJob(next);
        if (next.status === "succeeded" || next.status === "failed" || next.status === "cancelled") {
          return;
        }
      } catch {
        if (cancelled) return;
      }
      timerRef.current = setTimeout(poll, 1200);
    };

    void poll();

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [jobId]);

  return job;
}

export function useDocumentMutations() {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["documents"] });
    queryClient.invalidateQueries({ queryKey: ["document"] });
    queryClient.invalidateQueries({ queryKey: ["species"] });
    queryClient.invalidateQueries({ queryKey: ["manage"] });
  };

  const upload = useMutation({
    mutationFn: (form: FormData) => documentsApi.upload(form),
    onSuccess: invalidate,
  });

  const addVersion = useMutation({
    mutationFn: ({ documentId, form }: { documentId: string; form: FormData }) =>
      documentsApi.addVersion(documentId, form),
    onSuccess: invalidate,
  });

  const rollback = useMutation({
    mutationFn: ({ documentId, versionId }: { documentId: string; versionId: string }) =>
      documentsApi.rollback(documentId, versionId),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (documentId: string) => documentsApi.remove(documentId),
    onSuccess: invalidate,
  });

  const retryJob = useMutation({
    mutationFn: (jobId: string) => documentsApi.retryJob(jobId),
    onSuccess: invalidate,
  });

  return { upload, addVersion, rollback, remove, retryJob, invalidate };
}
