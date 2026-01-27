import { useCallback, useRef, useState } from "react";
import {
  BaseFilters,
  classifyQuery,
  SearchDocWithContent,
  searchDocuments,
  SearchFlowClassificationResponse,
  SearchFullResponse,
} from "@/lib/search/searchApi";
import { useAppMode } from "@/providers/AppModeProvider";

export type QueryClassification = "search" | "chat" | "pending" | null;

export interface UseQueryControllerOptions {
  /** Callback invoked when the query should be handled as a chat */
  onChat: (query: string) => void;
}

export interface UseQueryControllerReturn {
  /** The query that was submitted */
  query: string | null;
  /** Classification state: null (idle), "pending" (classifying), "search", or "chat" */
  classification: QueryClassification;
  /** Search results (empty if chat or not yet searched) */
  searchResults: SearchDocWithContent[];
  /** Query expansions that were executed */
  executedQueries: string[];
  /** Document IDs selected by the LLM as most relevant */
  llmSelectedDocIds: string[] | null;
  /** Whether a search is currently in progress */
  isSearchLoading: boolean;
  /** Error message if search failed */
  searchError: string | null;
  /** Submit a query - routes to search or chat based on app mode */
  submit: (query: string, filters?: BaseFilters) => Promise<void>;
  /** Reset all state to initial values */
  reset: () => void;
}

/**
 * Unified hook for query handling - classification and search.
 *
 * Routes queries based on the current app mode:
 * - "chat" mode: immediately calls onChat callback
 * - "search" mode: performs document search
 * - "auto" mode: classifies query first, then routes accordingly
 *
 * @example
 * ```tsx
 * const queryController = useQueryController({
 *   onChat: (query) => {
 *     onSubmit({ message: query, files, deepResearch });
 *   }
 * });
 *
 * // For new sessions, use the controller's submit
 * <ChatInputBar onSubmit={queryController.submit} />
 *
 * // Check classification for UI state
 * if (queryController.classification === null) {
 *   // Show welcome message
 * }
 * ```
 */
export function useQueryController(
  options: UseQueryControllerOptions
): UseQueryControllerReturn {
  const { onChat } = options;
  const { appMode } = useAppMode();

  // Query state
  const [query, setQuery] = useState<string | null>(null);
  const [classification, setClassification] =
    useState<QueryClassification>(null);

  // Search state
  const [searchResults, setSearchResults] = useState<SearchDocWithContent[]>(
    []
  );
  const [executedQueries, setExecutedQueries] = useState<string[]>([]);
  const [llmSelectedDocIds, setLlmSelectedDocIds] = useState<string[] | null>(
    null
  );
  const [isSearchLoading, setIsSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Abort controllers for in-flight requests
  const classifyAbortRef = useRef<AbortController | null>(null);
  const searchAbortRef = useRef<AbortController | null>(null);

  /**
   * Perform document search
   */
  const performSearch = useCallback(
    async (searchQuery: string, filters?: BaseFilters): Promise<void> => {
      // Abort any previous search request
      if (searchAbortRef.current) {
        searchAbortRef.current.abort();
      }

      const controller = new AbortController();
      searchAbortRef.current = controller;

      setIsSearchLoading(true);
      setSearchError(null);

      try {
        const response: SearchFullResponse = await searchDocuments(
          searchQuery,
          {
            filters,
            numHits: 50,
            includeContent: false,
            signal: controller.signal,
          }
        );

        // Check if the response contains an error
        if (response.error) {
          setSearchError(response.error);
          setSearchResults([]);
          setExecutedQueries([]);
          setLlmSelectedDocIds(null);
          return;
        }

        setSearchResults(response.search_docs);
        setExecutedQueries(response.all_executed_queries);
        setLlmSelectedDocIds(response.llm_selected_doc_ids ?? null);
      } catch (err) {
        // Don't update state if the request was aborted
        if (err instanceof Error && err.name === "AbortError") {
          return;
        }

        const errorMessage =
          err instanceof Error ? err.message : "Search failed";
        console.error("Document search failed:", err);
        setSearchError(errorMessage);
        setSearchResults([]);
        setExecutedQueries([]);
        setLlmSelectedDocIds(null);
      } finally {
        // Only update loading state if this is still the active request
        if (searchAbortRef.current === controller) {
          setIsSearchLoading(false);
        }
      }
    },
    []
  );

  /**
   * Classify a query as search or chat
   */
  const performClassification = useCallback(
    async (classifyQueryText: string): Promise<"search" | "chat"> => {
      // Abort any previous classification request
      if (classifyAbortRef.current) {
        classifyAbortRef.current.abort();
      }

      const controller = new AbortController();
      classifyAbortRef.current = controller;

      setClassification("pending");

      try {
        const response: SearchFlowClassificationResponse = await classifyQuery(
          classifyQueryText,
          controller.signal
        );

        const result = response.is_search_flow ? "search" : "chat";
        setClassification(result);
        return result;
      } catch (error) {
        // Re-throw abort errors so caller can handle
        if (error instanceof Error && error.name === "AbortError") {
          throw error;
        }

        console.error("Query classification failed:", error);
        // Default to chat flow on error (matches backend behavior)
        setClassification("chat");
        return "chat";
      }
    },
    []
  );

  /**
   * Submit a query - routes based on app mode
   */
  const submit = useCallback(
    async (submitQuery: string, filters?: BaseFilters): Promise<void> => {
      setQuery(submitQuery);

      // Chat mode: skip classification, go directly to chat
      if (appMode === "chat") {
        setClassification("chat");
        setSearchResults([]);
        setExecutedQueries([]);
        setLlmSelectedDocIds(null);
        onChat(submitQuery);
        return;
      }

      // Search mode: skip classification, go directly to search
      if (appMode === "search") {
        setClassification("search");
        await performSearch(submitQuery, filters);
        return;
      }

      // Auto mode: classify first, then route
      try {
        const result = await performClassification(submitQuery);

        if (result === "search") {
          await performSearch(submitQuery, filters);
        } else {
          // Clear any previous search results when going to chat
          setSearchResults([]);
          setExecutedQueries([]);
          setLlmSelectedDocIds(null);
          onChat(submitQuery);
        }
      } catch (error) {
        // If classification was aborted, do nothing
        if (error instanceof Error && error.name === "AbortError") {
          return;
        }

        // On other errors, default to chat
        setSearchResults([]);
        setExecutedQueries([]);
        setLlmSelectedDocIds(null);
        onChat(submitQuery);
      }
    },
    [appMode, onChat, performClassification, performSearch]
  );

  /**
   * Reset all state to initial values
   */
  const reset = useCallback(() => {
    // Abort any in-flight requests
    if (classifyAbortRef.current) {
      classifyAbortRef.current.abort();
      classifyAbortRef.current = null;
    }
    if (searchAbortRef.current) {
      searchAbortRef.current.abort();
      searchAbortRef.current = null;
    }

    setQuery(null);
    setClassification(null);
    setSearchResults([]);
    setExecutedQueries([]);
    setLlmSelectedDocIds(null);
    setIsSearchLoading(false);
    setSearchError(null);
  }, []);

  return {
    query,
    classification,
    searchResults,
    executedQueries,
    llmSelectedDocIds,
    isSearchLoading,
    searchError,
    submit,
    reset,
  };
}
