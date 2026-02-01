/**
 * Search API Types
 *
 * These types match the backend models in:
 * - backend/ee/onyx/server/query_and_chat/models.py
 * - backend/ee/onyx/server/query_and_chat/search_backend.py
 * - backend/onyx/context/search/models.py
 */

import { ValidSources } from "../types";

// ============================================================================
// Classification API
// ============================================================================

/**
 * Request to classify a query as search or chat flow
 * POST /api/search/search-flow-classification
 */
export interface SearchFlowClassificationRequest {
  user_query: string;
}

/**
 * Response from query classification
 */
export interface SearchFlowClassificationResponse {
  is_search_flow: boolean;
}

// ============================================================================
// Search API
// ============================================================================

/**
 * Base filters for search queries
 * Matches backend/onyx/context/search/models.py BaseFilters
 */
export interface BaseFilters {
  source_type?: ValidSources[] | null;
  document_set?: string[] | null;
  time_cutoff?: string | null; // ISO date string
  tags?: Array<{ tag_key: string; tag_value: string }> | null;
}

/**
 * Request to perform a document search
 * POST /api/search/send-search-message
 */
export interface SendSearchQueryRequest {
  search_query: string;
  filters?: BaseFilters | null;
  num_docs_fed_to_llm_selection?: number | null;
  run_query_expansion?: boolean;
  num_hits?: number; // default 50
  include_content?: boolean;
  stream?: boolean;
}

/**
 * Search document with optional content
 * Matches backend SearchDocWithContent
 */
export interface SearchDocWithContent {
  document_id: string;
  chunk_ind: number;
  semantic_identifier: string;
  link: string | null;
  blurb: string;
  source_type: ValidSources;
  boost: number;
  hidden: boolean;
  metadata: Record<string, string | string[]>;
  score: number | null;
  is_relevant?: boolean | null;
  relevance_explanation?: string | null;
  match_highlights: string[];
  updated_at: string | null; // ISO date string
  primary_owners?: string[] | null;
  secondary_owners?: string[] | null;
  is_internet: boolean;
  content?: string | null;
}

/**
 * Full response from a search query (non-streaming)
 */
export interface SearchFullResponse {
  all_executed_queries: string[];
  search_docs: SearchDocWithContent[];
  doc_selection_reasoning?: string | null;
  llm_selected_doc_ids?: string[] | null;
  error?: string | null;
}

// ============================================================================
// Search History API
// ============================================================================

/**
 * Single search query in history
 */
export interface SearchQueryResponse {
  query: string;
  query_expansions: string[] | null;
  created_at: string; // ISO date string
}

/**
 * Response from search history endpoint
 * GET /api/search/search-history
 */
export interface SearchHistoryResponse {
  search_queries: SearchQueryResponse[];
}

// ============================================================================
// Streaming Packets (for stream=true)
// ============================================================================

export interface SearchDocsPacket {
  type: "search_docs";
  search_docs: SearchDocWithContent[];
}

export interface SearchErrorPacket {
  type: "search_error";
  error: string;
}

export interface LLMSelectedDocsPacket {
  type: "llm_selected_docs";
  llm_selected_doc_ids: string[] | null;
}

export interface QueryExpansionsPacket {
  type: "query_expansions";
  executed_queries: string[];
}

export interface DocSelectionReasoningPacket {
  type: "doc_selection_reasoning";
  reasoning: string;
}

export type SearchStreamPacket =
  | SearchDocsPacket
  | SearchErrorPacket
  | LLMSelectedDocsPacket
  | QueryExpansionsPacket
  | DocSelectionReasoningPacket;

// ============================================================================
// API Helper Functions
// ============================================================================

/**
 * Classify a query as search or chat flow
 */
export async function classifyQuery(
  query: string,
  signal?: AbortSignal
): Promise<SearchFlowClassificationResponse> {
  const response = await fetch("/api/search/search-flow-classification", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_query: query,
    } as SearchFlowClassificationRequest),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Classification failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Perform a document search
 */
export async function searchDocuments(
  query: string,
  options?: {
    filters?: BaseFilters;
    numHits?: number;
    includeContent?: boolean;
    signal?: AbortSignal;
  }
): Promise<SearchFullResponse> {
  const request: SendSearchQueryRequest = {
    search_query: query,
    filters: options?.filters,
    num_hits: options?.numHits ?? 50,
    include_content: options?.includeContent ?? false,
    stream: false,
  };

  const response = await fetch("/api/search/send-search-message", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal: options?.signal,
  });

  if (!response.ok) {
    throw new Error(`Search failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Fetch search history for the current user
 */
export async function fetchSearchHistory(options?: {
  limit?: number;
  filterDays?: number;
  signal?: AbortSignal;
}): Promise<SearchHistoryResponse> {
  const params = new URLSearchParams();
  if (options?.limit) params.set("limit", options.limit.toString());
  if (options?.filterDays)
    params.set("filter_days", options.filterDays.toString());

  const response = await fetch(
    `/api/search/search-history?${params.toString()}`,
    {
      signal: options?.signal,
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch search history: ${response.statusText}`);
  }

  return response.json();
}
