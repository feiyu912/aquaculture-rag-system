/**
 * Shared helpers for the end-to-end suite.
 *
 * The suite runs against the *real* backend: it uploads real PDFs, waits for
 * the real ARQ worker to index them, and asserts on the real SSE stream. No
 * request is mocked.
 */
import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

export const API_BASE = process.env.AQUA_API_BASE ?? "http://127.0.0.1:8000";
export const FIXTURES = path.resolve(process.cwd(), "e2e/fixtures");

/** Mirrors `UploadResponse` in `apps/api/app/schemas.py` (snake_case). */
export interface UploadResult {
  document_id: string;
  version_id: string;
  job_id: string;
  status: string;
}

/**
 * Remove documents created by earlier test runs.
 *
 * The backend rejects an upload whose content hash is already known, so a
 * failed run would otherwise poison every later run.
 */
export async function cleanupE2EDocuments(
  request: APIRequestContext,
  prefix = "E2E ",
): Promise<void> {
  const response = await request.get(`${API_BASE}/api/documents`);
  if (!response.ok()) return;
  const documents = (await response.json()) as { id: string; title: string }[];
  for (const document of documents) {
    if (!document.title.startsWith(prefix)) continue;
    const removed = await request.delete(`${API_BASE}/api/documents/${document.id}`);
    if (!removed.ok()) {
      throw new Error(
        `cleanup failed for ${document.title} (HTTP ${removed.status()}): ${await removed.text()}`,
      );
    }
  }
}

/** Upload a PDF and wait until the ARQ job has finished indexing it. */
export async function uploadPdf(
  page: Page,
  fileName: string,
  options: { title?: string; category?: string; species?: string } = {},
): Promise<UploadResult> {
  await cleanupE2EDocuments(page.request);

  const buffer = readFileSync(path.join(FIXTURES, fileName));
  const response = await page.request.post(`${API_BASE}/api/documents`, {
    multipart: {
      file: { name: fileName, mimeType: "application/pdf", buffer },
      ...(options.title ? { title: options.title } : {}),
      ...(options.category ? { category: options.category } : {}),
      ...(options.species ? { species: options.species } : {}),
    },
  });

  if (!response.ok()) {
    throw new Error(
      `upload ${fileName} failed (HTTP ${response.status()}): ${await response.text()}`,
    );
  }
  const body = (await response.json()) as UploadResult;

  await waitForJob(page, body.job_id);
  return body;
}

export async function waitForJob(page: Page, jobId: string, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  let last: Record<string, unknown> = {};
  while (Date.now() < deadline) {
    const response = await page.request.get(`${API_BASE}/api/jobs/${jobId}`);
    if (!response.ok()) {
      throw new Error(
        `job ${jobId} query failed (HTTP ${response.status()}): ${await response.text()}`,
      );
    }
    last = (await response.json()) as Record<string, unknown>;
    const status = String(last.status);
    if (status === "succeeded") return last;
    if (status === "failed" || status === "cancelled") {
      throw new Error(
        `ingest job ${jobId} ended as ${status}: ${String(last.error_message ?? last.error_code ?? "")}`,
      );
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`ingest job ${jobId} did not finish in ${timeoutMs}ms: ${JSON.stringify(last)}`);
}

/** Ask a question and return the streamed SSE frames for the whole answer. */
export async function streamChat(
  page: Page,
  question: string,
  options: { sessionId?: string; mode?: string; species?: string } = {},
): Promise<{ events: Record<string, unknown>[]; text: string; sources: unknown[] }> {
  const events: Record<string, unknown>[] = [];
  const sources: unknown[] = [];
  let text = "";

  const result = await page.evaluate(
    async (payload) => {
      const response = await fetch("http://127.0.0.1:8000/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok || !response.body) {
        return { error: `HTTP ${response.status}`, frames: [] as Record<string, unknown>[] };
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const frames: Record<string, unknown>[] = [];

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index = buffer.indexOf("\n\n");
        while (index !== -1) {
          const raw = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          let event = "message";
          const data: string[] = [];
          for (const line of raw.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data.push(line.slice(5).trim());
          }
          if (data.length) {
            try {
              frames.push({ event, data: JSON.parse(data.join("\n")) });
            } catch {
              frames.push({ event, data: null });
            }
          }
          index = buffer.indexOf("\n\n");
        }
      }
      return { error: null, frames };
    },
    {
      question,
      session_id: options.sessionId ?? null,
      retrieval_mode: options.mode ?? "hybrid",
      species: options.species ?? null,
    },
  );

  if (result.error) throw new Error(`chat stream failed: ${result.error}`);

  for (const frame of result.frames) {
    events.push(frame);
    const data = frame.data as Record<string, unknown> | null;
    if (!data) continue;
    if (frame.event === "token") text += String(data.text ?? "");
    if (frame.event === "sources") sources.push(...((data.sources as unknown[]) ?? []));
  }

  return { events, text, sources };
}
