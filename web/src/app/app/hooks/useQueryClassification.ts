import { useCallback, useRef, useState } from "react";
import {
  classifyQuery,
  SearchFlowClassificationResponse,
} from "@/lib/search/searchApi";

export interface UseQueryClassificationReturn {
  /** Whether the last classified query was a search flow (true) or chat flow (false) */
  isSearchFlow: boolean | null;
  /** Whether classification is currently in progress */
  isClassifying: boolean;
  /** Classify a query and return whether it's a search flow */
  classify: (query: string) => Promise<boolean>;
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
 * const { isSearchFlow, isClassifying, classify } = useQueryClassification();
 *
 * const handleSubmit = async (query: string) => {
 *   const isSearch = await classify(query);
 *   if (isSearch) {
 *     // Show search results UI
 *   } else {
 *     // Start chat session
 *   }
 * };
 * ```
 */
export function useQueryClassification(): UseQueryClassificationReturn {
  const [isSearchFlow, setIsSearchFlow] = useState<boolean | null>(null);
  const [isClassifying, setIsClassifying] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const classify = useCallback(
    async (query: string): Promise<boolean> => {
      // Abort any previous in-flight request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const controller = new AbortController();
      abortControllerRef.current = controller;

      setIsClassifying(true);

      try {
        const response: SearchFlowClassificationResponse = await classifyQuery(
          query,
          controller.signal
        );

        setIsSearchFlow(response.is_search_flow);
        return response.is_search_flow;
      } catch (error) {
        // Don't update state if the request was aborted
        if (error instanceof Error && error.name === "AbortError") {
          // Return the previous state or default to false
          return isSearchFlow ?? false;
        }

        console.error("Query classification failed:", error);
        // Default to chat flow on error (matches backend behavior)
        setIsSearchFlow(false);
        return false;
      } finally {
        // Only update loading state if this is still the active request
        if (abortControllerRef.current === controller) {
          setIsClassifying(false);
        }
      }
    },
    [isSearchFlow]
  );

  const reset = useCallback(() => {
    // Abort any in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    setIsSearchFlow(null);
    setIsClassifying(false);
  }, []);

  return {
    isSearchFlow,
    isClassifying,
    classify,
    reset,
  };
}
