/**
 * Search API Helper Functions
 */

import type {
  BaseFilters,
  SearchFlowClassificationRequest,
  SearchFlowClassificationResponse,
  SearchFullResponse,
  SearchHistoryResponse,
  SendSearchQueryRequest,
} from "@/lib/search/interfaces";

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
    num_hits: options?.numHits ?? 30,
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
