import { useCallback, useRef, useState } from "react";
import {
  classifyQuery,
  SearchFlowClassificationResponse,
} from "@/lib/search/searchApi";

export type QueryClassification = "search" | "chat" | "pending";

export interface UseQueryClassificationReturn {
  /** The classification result of the last query, or null if not yet classified */
  queryClassification: QueryClassification | null;
  /** Classify a query - result will be available via queryClassification */
  classify: (query: string) => Promise<void>;
  /** Reset the classification state */
  reset: () => void;
}

/**
 * Hook to classify user queries as search or chat flow.
 *
 * Uses the backend classification endpoint which applies LLM-based
 * classification with a 2-second timeout. Queries over 200 characters
 * are automatically classified as chat.
 *
 * @example
 * ```tsx
 * const { queryClassification, isClassifying, classify } = useQueryClassification();
 *
 * const handleSubmit = async (query: string) => {
 *   await classify(query);
 *   // After classify resolves, check queryClassification state
 * };
 *
 * // React to classification changes
 * useEffect(() => {
 *   if (queryClassification === "search") {
 *     // Show search results UI
 *   } else if (queryClassification === "chat") {
 *     // Start chat session
 *   }
 * }, [queryClassification]);
 * ```
 */
export default function useQueryClassification(): UseQueryClassificationReturn {
  const [queryClassification, setQueryClassification] =
    useState<QueryClassification | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const classify = useCallback(async (query: string): Promise<void> => {
    // Abort any previous in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response: SearchFlowClassificationResponse = await classifyQuery(
        query,
        controller.signal
      );

      setQueryClassification(response.is_search_flow ? "search" : "chat");
    } catch (error) {
      // Don't update state if the request was aborted
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }

      console.error("Query classification failed:", error);
      // Default to chat flow on error (matches backend behavior)
      setQueryClassification("chat");
    }
  }, []);

  const reset = useCallback(() => {
    // Abort any in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    // setQueryClassification(null);
  }, []);

  return {
    queryClassification,
    classify,
    reset,
  };
}
