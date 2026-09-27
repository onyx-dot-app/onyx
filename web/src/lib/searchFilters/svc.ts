import { SearchFiltersRequest } from "@/lib/searchFilters/types";

/**
 * Runs a document search against the admin endpoint.
 *
 * The same filters the chat sends as `internal_search_filters`, pointed at a
 * direct search instead: no agent, no LLM, no tool invocation. It is the other
 * consumer of {@link SearchFiltersRequest}, and why these filters are not named
 * for the search tool.
 */
export async function adminSearch(
  query: string,
  filters: SearchFiltersRequest
) {
  return await fetch("/api/admin/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      filters,
    }),
  });
}
