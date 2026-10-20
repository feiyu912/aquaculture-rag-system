import { ApiError, API_BASE_URL, apiFetch } from "./client";
import type {
  ChatDoneEvent,
  ChatStatusEvent,
  CitationReport,
  RetrievalMode,
  Source,
} from "./types";

export interface ChatRequestBody {
  question: string;
  session_id?: string | null;
  category?: string | null;
  species?: string | null;
  retrieval_mode?: RetrievalMode;
}

export interface ChatStreamHandlers {
  onMeta?: (payload: { request_id: string; session_id: string; message_id: string }) => void;
  onStatus?: (payload: ChatStatusEvent) => void;
  onSources?: (sources: Source[]) => void;
  onToken?: (text: string) => void;
  onCitationCheck?: (report: CitationReport) => void;
  onDone?: (payload: ChatDoneEvent) => void;
  onServerError?: (payload: { code: string; message: string; retryable: boolean }) => void;
}

interface SseFrame {
  event: string;
  data: string;
}

/**
 * Parse a raw SSE byte stream into frames.
 *
 * The backend writes `event: <name>\ndata: <json>\n\n` frames. We buffer
 * partial frames across chunk boundaries because TCP does not preserve
 * message boundaries.
 */
async function* readFrames(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseFrame> {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const frame = parseFrame(raw);
        if (frame) yield frame;
        boundary = buffer.indexOf("\n\n");
      }
    }
    const tail = parseFrame(buffer);
    if (tail) yield tail;
  } finally {
    reader.releaseLock();
  }
}

function parseFrame(raw: string): SseFrame | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of raw.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }

  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}

/**
 * POST + SSE. `EventSource` cannot issue POST requests, so we consume the
 * response body as a stream and decode SSE frames by hand. The returned
 * promise rejects on transport failures; server-sent `error` events are
 * surfaced through `onServerError` so the UI can distinguish a failed
 * generation from a failed connection.
 */
export async function streamChat(
  body: ChatRequestBody,
  handlers: ChatStreamHandlers = {},
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        question: body.question,
        session_id: body.session_id ?? null,
        category: body.category ?? null,
        species: body.species ?? null,
        retrieval_mode: body.retrieval_mode ?? "hybrid",
      }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("无法连接到后端服务，请确认 FastAPI 已在 8000 端口运行。", {
      retryable: true,
      code: "network_error",
    });
  }

  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : (detail?.message as string | undefined) ?? `请求失败（HTTP ${response.status}）`;
    throw new ApiError(message, { status: response.status, detail, retryable: response.status >= 500 });
  }

  for await (const frame of readFrames(response.body)) {
    if (!frame.data) continue;
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(frame.data);
    } catch {
      continue;
    }

    switch (frame.event) {
      case "meta":
        handlers.onMeta?.(payload as never);
        break;
      case "status":
        handlers.onStatus?.(payload as never);
        break;
      case "sources":
        handlers.onSources?.((payload.sources as Source[]) ?? []);
        break;
      case "token":
        handlers.onToken?.((payload.text as string) ?? "");
        break;
      case "citation_check":
        handlers.onCitationCheck?.(payload as unknown as CitationReport);
        break;
      case "done":
        handlers.onDone?.(payload as unknown as ChatDoneEvent);
        break;
      case "error":
        handlers.onServerError?.({
          code: (payload.code as string) ?? "unknown",
          message: (payload.message as string) ?? "生成失败",
          retryable: payload.retryable !== false,
        });
        break;
      default:
        break;
    }
  }
}

export const chatApi = {
  stream: streamChat,
};

export const sessionsApi = {
  list: () => apiFetch<import("./types").SessionOut[]>("/api/sessions"),
  create: () =>
    apiFetch<import("./types").SessionOut>("/api/sessions", { method: "POST", body: "{}" }),
  messages: (sessionId: string) =>
    apiFetch<import("./types").MessageOut[]>(`/api/sessions/${sessionId}/messages`),
  remove: (sessionId: string) =>
    apiFetch<void>(`/api/sessions/${sessionId}`, { method: "DELETE" }),
};
