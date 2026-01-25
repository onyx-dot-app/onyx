import { useCallback, useRef, useState } from "react";
import {
  BaseFilters,
  SearchDocWithContent,
  searchDocuments,
  SearchFullResponse,
} from "@/lib/search/searchApi";

export interface UseDocumentSearchReturn {
  /** Search results */
  results: SearchDocWithContent[];
  /** Query expansions that were executed */
  executedQueries: string[];
  /** Document IDs selected by the LLM as most relevant */
  llmSelectedDocIds: string[] | null;
  /** LLM's reasoning for document selection */
  docSelectionReasoning: string | null;
  /** Whether a search is currently in progress */
  isLoading: boolean;
  /** Error message if search failed */
  error: string | null;
  /** Perform a document search */
  search: (query: string, filters?: BaseFilters) => Promise<void>;
  /** Reset the search state */
  reset: () => void;
}

/**
 * Hook to perform document searches.
 *
 * Uses the search endpoint which performs semantic/keyword search
 * and optionally applies LLM-based document selection.
 *
 * @example
 * ```tsx
 * const { results, isLoading, error, search } = useDocumentSearch();
 *
 * const handleSearch = async (query: string) => {
 *   await search(query, { source_type: ['confluence'] });
 *   // results are now populated
 * };
 * ```
 */
export function useDocumentSearch(): UseDocumentSearchReturn {
  const [results, setResults] = useState<SearchDocWithContent[]>([]);
  const [executedQueries, setExecutedQueries] = useState<string[]>([]);
  const [llmSelectedDocIds, setLlmSelectedDocIds] = useState<string[] | null>(
    null
  );
  const [docSelectionReasoning, setDocSelectionReasoning] = useState<
    string | null
  >(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const search = useCallback(
    async (query: string, filters?: BaseFilters): Promise<void> => {
      // Abort any previous in-flight request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const controller = new AbortController();
      abortControllerRef.current = controller;

      setIsLoading(true);
      setError(null);

      try {
        const response: SearchFullResponse = await searchDocuments(query, {
          filters,
          numHits: 50,
          includeContent: false,
          signal: controller.signal,
        });

        // Check if the response contains an error
        if (response.error) {
          setError(response.error);
          setResults([]);
          setExecutedQueries([]);
          setLlmSelectedDocIds(null);
          setDocSelectionReasoning(null);
          return;
        }

        setResults(response.search_docs);
        setExecutedQueries(response.all_executed_queries);
        setLlmSelectedDocIds(response.llm_selected_doc_ids ?? null);
        setDocSelectionReasoning(response.doc_selection_reasoning ?? null);
      } catch (err) {
        // Don't update state if the request was aborted
        if (err instanceof Error && err.name === "AbortError") {
          return;
        }

        const errorMessage =
          err instanceof Error ? err.message : "Search failed";
        console.error("Document search failed:", err);
        setError(errorMessage);
        setResults([]);
        setExecutedQueries([]);
        setLlmSelectedDocIds(null);
        setDocSelectionReasoning(null);
      } finally {
        // Only update loading state if this is still the active request
        if (abortControllerRef.current === controller) {
          setIsLoading(false);
        }
      }
    },
    []
  );

  const reset = useCallback(() => {
    // Abort any in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    setResults([]);
    setExecutedQueries([]);
    setLlmSelectedDocIds(null);
    setDocSelectionReasoning(null);
    setIsLoading(false);
    setError(null);
  }, []);

  return {
    results,
    executedQueries,
    llmSelectedDocIds,
    docSelectionReasoning,
    isLoading,
    error,
    search,
    reset,
  };
}
