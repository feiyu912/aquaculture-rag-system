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

/**
 * Mirrors the `source_aware_retrieval` trace in
 * `apps/api/app/retrieval/service.py` — per-source evidence reservation for
 * questions that explicitly cite two or more standards.
 */
export interface SourceAwareTrace {
  cited: { code: string; [key: string]: unknown }[];
  resolved: Record<string, string[]>;
  active: boolean;
  reason: string | null;
}

/**
 * Mirrors the `llm_planner` trace in
 * `apps/api/app/retrieval/service.py` / `apps/api/app/query/planner.py`.
 */
export interface PlannerTrace {
  enabled: boolean;
  used_llm?: boolean;
  error?: string | null;
  /** Set when the planner was intentionally not called (e.g. simple rule IR). */
  skipped?: string | null;
  duration_ms?: number;
  attempts?: number;
  plan?: Record<string, unknown> | null;
  original_question?: string;
  hard_filter?: string | null;
  subquestions?: string[];
  tasks?: Record<string, unknown>[];
  constraints?: {
    name: string;
    value: string;
    source: string;
    strength: string;
  }[];
  assumptions?: string[];
}

export interface TraceStageState {
  key: string;
  label: string;
  detail?: string;
  state: "on" | "off" | "skipped";
}
