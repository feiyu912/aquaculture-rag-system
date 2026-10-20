/**
 * TypeScript mirrors of the FastAPI contract in `apps/api/app/schemas.py`,
 * `apps/api/app/api/*` and `apps/api/app/retrieval/service.py`.
 *
 * These are hand-written on purpose: the backend is the source of truth and
 * we do not want to silently reshape its payloads. Any drift shows up as a
 * type error here rather than as a rendering bug at runtime.
 */

export type RetrievalMode = "dense" | "bm25" | "hybrid" | "hybrid_rerank";

export interface HealthResponse {
  status: "ok" | "degraded";
  components: Record<string, string>;
  collection: string;
  llm_provider: string;
  llm_configured: boolean;
  embedding_model: string;
  embedding_device: string;
  reranker_model: string;
}

/** Canonical bbox snapshot produced by `PyMuPDFParser._canonical_bbox`. */
export interface BBoxLocation {
  page: number;
  bbox: [number, number, number, number];
  coordinate_system: "pdf_points" | string;
  origin: "bottom-left" | string;
  rotation: number;
  page_width: number;
  page_height: number;
}

export interface Source {
  source_id: string;
  index: number;
  document_id: string;
  version_id: string;
  version_no: number;
  title: string;
  species: string[];
  page: number | null;
  quote: string;
  heading_path: string[];
  location: BBoxLocation | null;
}

export interface CitationOut {
  id: string;
  source_index: number;
  document_id: string;
  document_version_id: string;
  quote: string;
  page: number | null;
  bbox: BBoxLocation | null;
  score: number | null;
  support_status: string;
  support_score: number | null;
  /** Display metadata resolved server-side (may be null for deleted documents). */
  title: string | null;
  version_no: number | null;
  species: string[];
}

export interface MessageOut {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  status: string;
  created_at: string;
  citations: CitationOut[];
  model: string | null;
  latency_ms: number | null;
  meta: Record<string, unknown>;
}

export interface SessionOut {
  id: string;
  title: string;
  created_at: string;
  last_message_at: string | null;
}

export interface VersionOut {
  id: string;
  version_no: number;
  status: string;
  page_count: number;
  content_hash: string;
  error_message: string | null;
  created_at: string;
  activated_at: string | null;
}

export interface DocumentOut {
  id: string;
  title: string;
  category: string;
  species: string[];
  status: string;
  current_version_id: string | null;
  current_version_no: number | null;
  page_count: number | null;
  created_at: string;
}

export interface DocumentDetail extends DocumentOut {
  versions: VersionOut[];
}

export interface JobOut {
  id: string;
  document_version_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | string;
  progress: number;
  current_stage: string;
  error_code: string | null;
  error_message: string | null;
  metrics: Record<string, unknown>;
}

export interface UploadResponse {
  document_id: string;
  version_id: string;
  job_id: string;
  status: string;
}

/* ---------- Query IR (rule v1) ------------------------------------------ */

export interface QueryIR {
  original_question: string;
  intent: string;
  strategy: string;
  species: string[];
  species_filter: string | null;
  category_filter: string | null;
  stage: string[];
  water_metrics: string[];
  diseases: string[];
  years: number[];
  requires_current_regulation: boolean;
  unsupported_constraints: string[];
  warnings: string[];
}

export interface EvidenceGate {
  sufficient: boolean;
  reason: string;
  query_terms: string[];
  matched_terms: string[];
  matched_weight: number;
  total_weight: number;
  coverage: number;
  best_index: number | null;
  missing_terms: string[];
}

export interface ChatStatusEvent {
  stage: string;
  sources: number;
  active_versions: number;
  sufficient: boolean;
  retrieval_mode: RetrievalMode;
  species_filter: string | null;
  query_ir: QueryIR | null;
  adaptive_route: string | null;
  targeted_retrieval: unknown;
  graph_expansion: unknown;
  gate: EvidenceGate | null;
}

export interface CitationReport {
  valid: boolean;
  cited_indices: number[];
  invalid_indices: number[];
  cited_factual: number;
  factual_sentences: number;
  coverage: number;
  claim_summary?: {
    total: number;
    supported: number;
    weak: number;
    uncited: number;
    unverified?: number;
  };
  claims?: Array<{
    claim: string;
    cited_indices: number[];
    status: string;
    score: number;
    method: string;
    matched_terms: string[];
  }>;
}

export interface ChatTimings {
  dense_ms?: number;
  sparse_ms?: number;
  graph_ms?: number;
  retrieval_ms?: number;
  targeted_ms?: number;
  ttft_ms?: number | null;
  generation_ms?: number;
  total_ms?: number;
}

export interface TokenUsage {
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
}

export interface ChatDoneEvent {
  message_id: string;
  model: string;
  usage: TokenUsage;
  cost_usd: number;
  timings: ChatTimings;
  retrieval_mode: RetrievalMode;
  query_ir: QueryIR | null;
  adaptive_route: string | null;
  targeted_retrieval: unknown;
  graph_expansion: unknown;
  sufficient: boolean;
  gate: EvidenceGate | null;
  citation_check: CitationReport;
}

/* ---------- Debug trace ------------------------------------------------- */

export interface TraceRetrievalConfig {
  retrieval_mode?: string;
  species_filter?: string | null;
  category_filter?: string | null;
  embedding?: string;
  embedding_dimension?: number;
  reranker?: string;
  reranker_model?: string;
  collection?: string;
  dense_top_k?: number;
  bm25_top_k?: number;
  rrf_k?: number;
  rerank_top_k?: number;
  bm25?: Record<string, unknown>;
  adaptive_route?: string | null;
  adaptive_routing_enabled?: boolean;
  adaptive_modules?: Record<string, boolean>;
  graph_expansion?: unknown;
  graph_top_k?: number;
  graph_rrf_weight?: number;
  query_decomposition?: boolean;
  contextual_retrieval?: boolean;
  query_ir?: QueryIR | null;
  evidence_gate?: EvidenceGate;
  index_compatibility?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface TraceQueryVariant {
  query: string;
  weight: number;
  dense: number;
  sparse: number;
}

export interface QueryTrace {
  request_id: string;
  question: string;
  retrieval_config: TraceRetrievalConfig;
  query_ir: QueryIR | null;
  active_versions: string[];
  gate: EvidenceGate | null;
  timings: Record<string, number | null>;
  rankings: {
    dense?: string[];
    sparse?: string[];
    graph?: string[];
    queries?: TraceQueryVariant[];
    [key: string]: unknown;
  };
  fused_count: number;
  evidence: Source[];
  citation_check: CitationReport | null;
  model: string | null;
  cost_usd: number | null;
}
