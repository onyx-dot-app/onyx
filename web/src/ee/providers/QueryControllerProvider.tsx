"use client";

import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import {
  BaseFilters,
  SearchDocWithContent,
  SearchFlowClassificationResponse,
  SearchFullResponse,
} from "@/lib/search/interfaces";
import { classifyQuery, searchDocuments } from "@/ee/lib/search/svc";
import { useAppMode } from "@/providers/AppModeProvider";
import useAppFocus from "@/hooks/useAppFocus";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { useSettingsContext } from "@/providers/SettingsProvider";
import {
  QueryControllerContext,
  QueryControllerValue,
  QueryPhase,
} from "@/providers/QueryControllerProvider";

interface QueryControllerProviderProps {
  children: React.ReactNode;
}

export function QueryControllerProvider({
  children,
}: QueryControllerProviderProps) {
  const { appMode, setAppMode } = useAppMode();
  const appFocus = useAppFocus();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const settings = useSettingsContext();
  const { isSearchModeAvailable: searchUiEnabled } = settings;

  // Query state
  const [query, setQuery] = useState<string | null>(null);
  const [phase, setPhase] = useState<QueryPhase>("idle");

  // Search state
  const [searchResults, setSearchResults] = useState<SearchDocWithContent[]>(
    []
  );
  const [llmSelectedDocIds, setLlmSelectedDocIds] = useState<string[] | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);

  // Abort controllers for in-flight requests
  const classifyAbortRef = useRef<AbortController | null>(null);
  const searchAbortRef = useRef<AbortController | null>(null);

  /**
   * Perform document search (pure data-fetching, no phase/appMode side effects)
   */
  const performSearch = useCallback(
    async (searchQuery: string, filters?: BaseFilters): Promise<void> => {
      if (searchAbortRef.current) {
        searchAbortRef.current.abort();
      }

      const controller = new AbortController();
      searchAbortRef.current = controller;

      try {
        const response: SearchFullResponse = await searchDocuments(
          searchQuery,
          {
            filters,
            numHits: 30,
            includeContent: false,
            signal: controller.signal,
          }
        );

        if (response.error) {
          setError(response.error);
          setSearchResults([]);
          setLlmSelectedDocIds(null);
          return;
        }

        setError(null);
        setSearchResults(response.search_docs);
        setLlmSelectedDocIds(response.llm_selected_doc_ids ?? null);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") {
          return;
        }

        setError("Document search failed. Please try again.");
        setSearchResults([]);
        setLlmSelectedDocIds(null);
      }
    },
    []
  );

  /**
   * Classify a query as search or chat
   */
  const performClassification = useCallback(
    async (classifyQueryText: string): Promise<"search" | "chat"> => {
      if (classifyAbortRef.current) {
        classifyAbortRef.current.abort();
      }

      const controller = new AbortController();
      classifyAbortRef.current = controller;

      try {
        const response: SearchFlowClassificationResponse = await classifyQuery(
          classifyQueryText,
          controller.signal
        );

        const result = response.is_search_flow ? "search" : "chat";
        return result;
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          throw error;
        }

        setError("Query classification failed. Falling back to chat.");
        return "chat";
      }
    },
    []
  );

  /**
   * Submit a query - routes based on app mode
   */
  const submit = useCallback(
    async (
      submitQuery: string,
      onChat: (query: string) => void,
      filters?: BaseFilters
    ): Promise<void> => {
      setQuery(submitQuery);
      setError(null);

      // Always route through chat if:
      // 1. Not Enterprise Enabled
      // 2. Admin has disabled the Search UI
      // 3. Not in the "New Session" tab
      // 4. In "New Session" tab but app-mode is "Chat"
      if (
        !isPaidEnterpriseFeaturesEnabled ||
        !searchUiEnabled ||
        !appFocus.isNewSession() ||
        appMode === "chat"
      ) {
        setPhase("chat");
        setSearchResults([]);
        setLlmSelectedDocIds(null);
        onChat(submitQuery);
        return;
      }

      // Search mode: immediately show SearchUI with loading state
      if (appMode === "search") {
        setPhase("searching");
        await performSearch(submitQuery, filters);
        setPhase("search-results");
        setAppMode("search");
        return;
      }

      // Auto mode: classify first, then route
      setPhase("classifying");
      try {
        const result = await performClassification(submitQuery);

        if (result === "search") {
          setPhase("searching");
          await performSearch(submitQuery, filters);
          setPhase("search-results");
          setAppMode("search");
        } else {
          setPhase("chat");
          setSearchResults([]);
          setLlmSelectedDocIds(null);
          onChat(submitQuery);
        }
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          return;
        }

        setPhase("chat");
        setSearchResults([]);
        setLlmSelectedDocIds(null);
        onChat(submitQuery);
      }
    },
    [
      appMode,
      appFocus,
      performClassification,
      performSearch,
      isPaidEnterpriseFeaturesEnabled,
      searchUiEnabled,
      setAppMode,
    ]
  );

  /**
   * Re-run the current search query with updated server-side filters
   */
  const refineSearch = useCallback(
    async (filters: BaseFilters): Promise<void> => {
      if (!query) return;
      setPhase("searching");
      await performSearch(query, filters);
      setPhase("search-results");
    },
    [query, performSearch]
  );

  /**
   * Reset all state to initial values
   */
  const reset = useCallback(() => {
    if (classifyAbortRef.current) {
      classifyAbortRef.current.abort();
      classifyAbortRef.current = null;
    }
    if (searchAbortRef.current) {
      searchAbortRef.current.abort();
      searchAbortRef.current = null;
    }

    setQuery(null);
    setPhase("idle");
    setSearchResults([]);
    setLlmSelectedDocIds(null);
    setError(null);
  }, []);

  const value: QueryControllerValue = useMemo(
    () => ({
      phase,
      searchResults,
      llmSelectedDocIds,
      error,
      submit,
      refineSearch,
      reset,
    }),
    [
      phase,
      searchResults,
      llmSelectedDocIds,
      error,
      submit,
      refineSearch,
      reset,
    ]
  );

  // Sync state with navigation context
  useEffect(reset, [appFocus, reset]);

  return (
    <QueryControllerContext.Provider value={value}>
      {children}
    </QueryControllerContext.Provider>
  );
}
