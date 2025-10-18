import { useState, useEffect, useCallback, useRef } from "react";
import { searchQdrantDocuments } from "../qdrantUtils";
import { QdrantSearchResult } from "../qdrantInterfaces";

interface UseQdrantSearchOptions {
  searchQuery: string;
  enabled?: boolean;
  debounceMs?: number;
  limit?: number;
}

interface UseQdrantSearchResult {
  results: QdrantSearchResult[];
  isLoading: boolean;
  error: Error | null;
}

export function useQdrantSearch({
  searchQuery,
  enabled = true,
  debounceMs = 500,
  limit = 10,
}: UseQdrantSearchOptions): UseQdrantSearchResult {
  const [results, setResults] = useState<QdrantSearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const currentAbortController = useRef<AbortController | null>(null);
  const activeSearchIdRef = useRef<number>(0);

  const performSearch = useCallback(
    async (query: string, searchId: number, signal: AbortSignal) => {
      try {
        setIsLoading(true);
        setError(null);

        const response = await searchQdrantDocuments({
          query,
          limit,
          signal,
        });

        // Only update state if this is still the active search
        if (activeSearchIdRef.current === searchId && !signal.aborted) {
          setResults(response.results);
        }
      } catch (err: any) {
        if (
          err?.name !== "AbortError" &&
          activeSearchIdRef.current === searchId
        ) {
          console.error("Error searching Qdrant:", err);
          setError(err);
          setResults([]);
        }
      } finally {
        if (activeSearchIdRef.current === searchId) {
          setIsLoading(false);
        }
      }
    },
    [limit]
  );

  useEffect(() => {
    // Clear any pending timeouts
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
      searchTimeoutRef.current = null;
    }

    // Abort any in-flight requests
    if (currentAbortController.current) {
      currentAbortController.current.abort();
      currentAbortController.current = null;
    }

    // If search is disabled or query is empty, clear results
    if (!enabled || !searchQuery.trim()) {
      setResults([]);
      setIsLoading(false);
      setError(null);
      return;
    }

    // Clear old results immediately when query changes for better UX
    setResults([]);
    setIsLoading(true);

    // Create a new search ID
    const newSearchId = activeSearchIdRef.current + 1;
    activeSearchIdRef.current = newSearchId;

    // Create abort controller
    const controller = new AbortController();
    currentAbortController.current = controller;

    // Debounce the search
    searchTimeoutRef.current = setTimeout(() => {
      performSearch(searchQuery.trim(), newSearchId, controller.signal);
    }, debounceMs);

    // Cleanup function
    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
      controller.abort();
    };
  }, [searchQuery, enabled, debounceMs, performSearch]);

  return {
    results,
    isLoading,
    error,
  };
}
