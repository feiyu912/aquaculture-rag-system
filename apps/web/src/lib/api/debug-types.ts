/**
 * Types for the local debugging endpoints in `apps/api/app/api/debug.py`.
 */

export interface DebugStats {
  window_hours: number;
  queries: number;
  refusals: number;
  refusal_rate: number;
  routes: Record<string, number>;
  models: Record<string, number>;
  avg_retrieval_ms: number;
  p95_retrieval_ms: number;
  avg_total_ms: number;
  p95_total_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
}

export interface PlannerTrace {
  enabled: boolean;
  used_llm?: boolean;
  error?: string | null;
  duration_ms?: number;
  attempts?: number;
  plan?: Record<string, unknown> | null;
  hard_filter?: string | null;
  subquestions?: string[];
}

export interface TraceStageState {
  key: string;
  label: string;
  detail?: string;
  state: "on" | "off" | "skipped";
}
