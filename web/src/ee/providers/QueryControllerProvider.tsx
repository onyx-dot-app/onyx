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
  QueryClassification,
  QueryControllerValue,
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
  const [classification, setClassification] =
    useState<QueryClassification>(null);
  const [isClassifying, setIsClassifying] = useState(false);

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
   * Perform document search
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
      } finally {
        // After we've performed a search, we automatically switch to "search" mode.
        // This is a "sticky" implementation; on purpose.
        setAppMode("search");
      }
    },
    [setAppMode]
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

      setIsClassifying(true);

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
      } finally {
        setIsClassifying(false);
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

      // 1.
      // We always route through chat if we're not Enterprise Enabled.
      //
      // 2.
      // We always route through chat if the admin has disabled the Search UI.
      //
      // 3.
      // We only go down the classification route if we're in the "New Session" tab.
      // Everywhere else, we always use the chat-flow.
      //
      // 4.
      // If we're in the "New Session" tab and the app-mode is "Chat", we continue with the chat-flow anyways.
      if (
        !isPaidEnterpriseFeaturesEnabled ||
        !searchUiEnabled ||
        !appFocus.isNewSession() ||
        appMode === "chat"
      ) {
        setClassification("chat");
        setSearchResults([]);
        setLlmSelectedDocIds(null);
        onChat(submitQuery);
        return;
      }

      if (appMode === "search") {
        await performSearch(submitQuery, filters);
        setClassification("search");
        return;
      }

      // # Note (@raunakab)
      //
      // Interestingly enough, for search, we do:
      // 1. setClassification("search")
      // 2. performSearch
      //
      // But for chat, we do:
      // 1. performChat
      // 2. setClassification("chat")
      //
      // The ChatUI has a nice loading UI, so it's fine for us to prematurely set the
      // classification-state before the chat has finished loading.
      //
      // However, the SearchUI does not. Prematurely setting the classification-state
      // will lead to a slightly ugly UI.

      // Auto mode: classify first, then route
      try {
        const result = await performClassification(submitQuery);

        if (result === "search") {
          await performSearch(submitQuery, filters);
          setClassification("search");
        } else {
          setClassification("chat");
          setSearchResults([]);
          setLlmSelectedDocIds(null);
          onChat(submitQuery);
        }
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          return;
        }

        setClassification("chat");
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
    ]
  );

  /**
   * Re-run the current search query with updated server-side filters
   */
  const refineSearch = useCallback(
    async (filters: BaseFilters): Promise<void> => {
      if (!query) return;
      await performSearch(query, filters);
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
    setClassification(null);
    setSearchResults([]);
    setLlmSelectedDocIds(null);
    setError(null);
  }, []);

  const value: QueryControllerValue = useMemo(
    () => ({
      classification,
      isClassifying,
      searchResults,
      llmSelectedDocIds,
      error,
      submit,
      refineSearch,
      reset,
    }),
    [
      classification,
      isClassifying,
      searchResults,
      llmSelectedDocIds,
      error,
      submit,
      refineSearch,
      reset,
    ]
  );

  // Sync classification state with navigation context
  useEffect(reset, [appFocus, reset]);

  return (
    <QueryControllerContext.Provider value={value}>
      {children}
    </QueryControllerContext.Provider>
  );
}
