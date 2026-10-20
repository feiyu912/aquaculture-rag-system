import type {
  ChatTimings,
  CitationReport,
  EvidenceGate,
  QueryIR,
  RetrievalMode,
  Source,
} from "@/lib/api/types";

export type ChatMessageStatus = "completed" | "streaming" | "failed" | "interrupted";

export interface ChatMessage {
  /** Local id — for optimistic messages this is not the backend id. */
  id: string;
  backendId?: string;
  role: "user" | "assistant";
  content: string;
  status: ChatMessageStatus;
  createdAt: string;
  sources?: Source[];
  citationCheck?: CitationReport;
  error?: { message: string; retryable: boolean };
  requestId?: string;
  meta?: {
    model?: string;
    timings?: ChatTimings;
    retrievalMode?: RetrievalMode;
    sufficient?: boolean;
    gate?: EvidenceGate | null;
    queryIr?: QueryIR | null;
    costUsd?: number;
    usage?: { prompt_tokens?: number | null; completion_tokens?: number | null };
  };
}

export interface ChatStatusState {
  stage: string;
  sources: number;
  sufficient: boolean;
  retrievalMode?: RetrievalMode;
  gate?: EvidenceGate | null;
  queryIr?: QueryIR | null;
  /** Planner trace from the `status` SSE event. */
  llmPlanner?: import("@/lib/api/debug-types").PlannerTrace | null;
}
