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
  /** Maximum number of sources handed to the model and persisted as citations. */
  max_sources?: number;
  rerank_top_k?: number;
}

/** Canonical bbox snapshot produced by `PyMuPDFParser._canonical_bbox`. */
/**
 * Evidence location.  PDF points carry page/bbox; HTML carries a paragraph
 * anchor; FAQ carries its id.  Keep the non-PDF fields optional so a caller
 * cannot accidentally paint a PDF box from a web/FAQ source.
 */
export interface BBoxLocation {
  page?: number;
  bbox?: [number, number, number, number];
  coordinate_system?: "pdf_points" | "html" | "faq" | string;
  origin?: "bottom-left" | string;
  rotation?: number;
  page_width?: number;
  page_height?: number;
  paragraph?: number;
  paragraph_index?: number;
  chunk_id?: string;
  faq_id?: string;
  [key: string]: unknown;
}

/**
 * `source_type` is the evidence branch (document vs FAQ); `media_type` is the
 * physical format (PDF / HTML / FAQ).  A FAQ has no document/version/page, and
 * an HTML page has no PDF bbox — never fill those with fake values.
 */
export type SourceType = "document" | "faq";
export type MediaType = "pdf" | "html" | "faq";

export interface Source {
  source_id: string;
  index: number;
  source_type: SourceType;
  media_type: MediaType;
  document_id: string | null;
  version_id: string | null;
  version_no: number;
  title: string;
  species: string[];
  page: number | null;
  /** Last page when a PDF parent block spans multiple pages. */
  page_end?: number | null;
  quote: string;
  heading_path: string[];
  location: BBoxLocation | null;
  /** Every PDF page/bbox; ``location`` is only the first one. */
  locations?: BBoxLocation[];
  /** FAQ identity; non-null only for media_type === "faq". */
  faq_id?: string | null;
  source_url?: string | null;
  evidence_level?: string;
  authority?: string;
  publisher?: string | null;
  supplemental?: boolean;
  available?: boolean;
  unavailable_reason?: string | null;
  /** Parent chunk id — links a source back to the retrieval candidate lists. */
  chunk_id?: string;
  /** Child chunk id — this is the id that appears in the RRF candidate list. */
  child_chunk_id?: string;
}

export interface CitationOut {
  id: string;
  source_index: number;
  document_id: string | null;
  document_version_id: string | null;
  source_type?: SourceType;
  media_type?: MediaType;
  faq_id?: string | null;
  quote: string;
  page: number | null;
  page_end?: number | null;
  /**
   * Historical compatibility field: older rows store the whole `location`
   * object here. New responses also carry a dedicated `location` field.
   */
  bbox: BBoxLocation | null;
  location?: BBoxLocation | null;
  locations?: BBoxLocation[];
  chunk_id?: string | null;
  score: number | null;
  support_status: string;
  support_score: number | null;
  /** Display metadata resolved server-side (may be null for deleted documents). */
  title: string | null;
  version_no: number | null;
  species: string[];
  source_url?: string | null;
  document_status?: string | null;
  available?: boolean;
  unavailable_reason?: string | null;
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
  source_org?: string | null;
  source_url?: string | null;
  publish_year?: number | null;
  document_status?: string | null;
  region?: string | null;
  source_type?: string;
  authority_level?: string;
  verification_status?: string;
  technical_review_status?: string;
  domain_review_status?: string;
  review_flags?: string[];
  effective_date?: string | null;
  fetched_at?: string | null;
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
  normalized_question: string;
  intent: string;
  strategy: string;
  species: string[];
  species_filter: string | null;
  category_filter: string | null;
  growth_stage: string[];
  water_parameters: string[];
  diseases: string[];
  requested_year: number | null;
  requires_current_regulation: boolean;
  unsupported_constraints: string[];
  warnings: string[];
  source: string;
  confidence: number;
  /**
   * "rules" or "llm" — whether the structure came from the rule parser or
   * from the LLM planner. Every `planner_*` field is empty for a rule-only
   * request.
   */
  planner_source: string;
  planner_confidence: number | null;
  planner_assumptions: string[];
  planner_constraints: {
    name: string;
    value: string;
    source: string;
    strength: string;
  }[];
  planner_subquestions: string[];
  planner_tasks: Record<string, unknown>[];
  rewritten_query: string | null;
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
  /** Planner trace; `null` when the rule-based IR was used. */
  llm_planner?: import("./debug-types").PlannerTrace | null;
  source_aware_retrieval?: import("./debug-types").SourceAwareTrace | null;
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
  llm_planner?: import("./debug-types").PlannerTrace | null;
  source_aware_retrieval?: import("./debug-types").SourceAwareTrace | null;
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
  fused?: string[];
  fused_count: number;
  evidence: Source[];
  citation_check: CitationReport | null;
  model: string | null;
  cost_usd: number | null;
}


/** ---- data-management API (`/api/manage/*`) ------------------------------ */

export interface ManagedDocument extends DocumentOut {
  updated_at: string;
  language: string | null;
  license: string | null;
  document_type: string;
  document_type_label: string;
  storage_policy: string;
  storage_policy_label: string;
  source_id: string | null;
  current_version_status: string | null;
  published: boolean;
  retrievable: boolean;
  parent_chunks: number;
  child_chunks: number;
}

export interface DocumentPage {
  items: ManagedDocument[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  has_next: boolean;
  has_prev: boolean;
  sort: string;
  applied_filters: Record<string, unknown>;
}

export interface ReviewFlag {
  code: string;
  label: string;
}

export interface ManagedVersion extends VersionOut {
  parser_name: string | null;
  parser_version: string | null;
  file_size: number;
  error_code: string | null;
  parent_chunks: number;
  child_chunks: number;
  job_status: string | null;
  job_id: string | null;
}

export interface ChunkPreview {
  id: string;
  chunk_role: "parent" | "child" | string;
  ordinal: number;
  page_from: number;
  page_to: number;
  heading_path: string[];
  content: string;
  truncated: boolean;
  locations: unknown[];
}

export interface JobSummary {
  id: string;
  document_id: string;
  document_version_id: string;
  document_title: string;
  version_no: number;
  job_type: string;
  status: string;
  progress: number;
  current_stage: string;
  attempts: number;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface ManagedDocumentDetail extends ManagedDocument {
  versions: ManagedVersion[];
  jobs: JobSummary[];
  chunks_preview: ChunkPreview[];
  review_flag_details: ReviewFlag[];
  source: Record<string, any>;
  storage: Record<string, any>;
  review: Record<string, any>;
}

export interface FaqSupport {
  document_id: string | null;
  version_id: string | null;
  chunk_id: string | null;
  title: string | null;
  version_no: number | null;
  page: number | null;
  quote: string | null;
  score: number | null;
  source_type: string | null;
  source_url: string | null;
  available: boolean;
  unavailable_reason: string | null;
}

export interface ManagedFaq {
  id: string;
  question: string;
  answer: string;
  species: string[];
  topic: string | null;
  region: string | null;
  review_status: string;
  usage_scope: string;
  evidence_status: string;
  quality_flags: unknown[];
  source_dataset: string;
  source_authority: string;
  original_source_url: string | null;
  source_license: string | null;
  supporting_count: number;
  reviewer: string | null;
  reviewed_at: string | null;
  indexed_at: string | null;
  indexed: boolean;
  review_provenance: string;
  review_provenance_label: string;
  domain_review_status: string;
  supporting: FaqSupport[];
}

export interface FaqPage {
  items: ManagedFaq[];
  total: number;
  limit: number;
  offset: number;
}

export interface CatalogStats {
  generated_at: string;
  documents: {
    total: number;
    records_including_deleted: number;
    by_status: Record<string, number>;
    by_status_including_deleted?: Record<string, number>;
    by_verification: Record<string, number>;
    by_document_type: Record<string, number>;
    by_review_status: {
      technical: Record<string, number>;
      domain: Record<string, number>;
    };
    active: number;
    staging: number;
    failed: number;
    deleted: number;
    published: number;
    retrievable: number;
    with_current_version: number;
    independent_sources: {
      total: number;
      active: number;
      staging: number;
      effective: number;
      staging_with_current_version: number;
      duplicate_or_repeated_records: number;
    };
  };
  versions: {
    total: number;
    live_total: number;
    deleted_total: number;
    by_status: Record<string, number>;
    documents_with_multiple_versions: number;
  };
  chunks: Record<
    "all_versions" | "current_active" | "current_staging" | "deleted_versions",
    { parent: number; child: number; total: number }
  >;
  faq: {
    total: number;
    pending: number;
    verified: number;
    rejected: number;
    by_status: Record<string, number>;
    by_scope: Record<string, number>;
    by_evidence_status: Record<string, number>;
    verified_indexed: number;
    index_points: number | null;
    index_points_error: string | null;
  };
  sources: {
    registered: number;
    latest_crawl: Record<string, number>;
    latest_faq_import: Record<string, number>;
  };
}

export interface FacetValue {
  value: string;
  label?: string;
  count: number;
}

export interface CatalogFacets {
  status: FacetValue[];
  category: FacetValue[];
  species: FacetValue[];
  source_type: FacetValue[];
  authority_level: FacetValue[];
  technical_review_status: FacetValue[];
  domain_review_status: FacetValue[];
  language: FacetValue[];
  license: FacetValue[];
  document_type: FacetValue[];
}

export interface AnswerModeOption {
  value: "document_rag" | "document_faq_rag" | "faq_direct";
  label: string;
  hint: string;
  available: boolean;
  reason: string | null;
}

export interface Capabilities {
  default_answer_mode: "document_rag" | "document_faq_rag" | "faq_direct";
  faq_retrieval: boolean;
  faq_direct_answer: boolean;
  faq_supplement_k: number;
  max_sources: number;
  answer_modes: AnswerModeOption[];
  document_promotion: {
    available: boolean;
    requires: string[];
    note: string;
  };
}

export interface LlmConfig {
  provider: string;
  env_model: string;
  override_model: string | null;
  effective_model: string;
  switchable: boolean;
}
