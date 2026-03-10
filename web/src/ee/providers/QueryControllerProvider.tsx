"use client";

import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import {
  BaseFilters,
  SearchDocWithContent,
  SearchFlowClassificationResponse,
  SearchFullResponse,
} from "@/lib/search/interfaces";
import { classifyQuery, searchDocuments } from "@/ee/lib/search/svc";
import useAppFocus from "@/hooks/useAppFocus";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { useUser } from "@/providers/UserProvider";
import {
  QueryControllerContext,
  QueryControllerValue,
  QueryState,
  AppMode,
} from "@/providers/QueryControllerProvider";

interface QueryControllerProviderProps {
  children: React.ReactNode;
}

export function QueryControllerProvider({
  children,
}: QueryControllerProviderProps) {
  const appFocus = useAppFocus();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const settings = useSettingsContext();
  const { isSearchModeAvailable: searchUiEnabled } = settings;
  const { user } = useUser();

  // ── Merged query state (discriminated union) ──────────────────────────
  const [state, setState] = useState<QueryState>({
    phase: "idle",
    appMode: "chat",
  });

  // Persistent app-mode preference — survives phase transitions and is
  // used to restore the correct mode when resetting back to idle.
  const appModeRef = useRef<AppMode>("chat");

  // ── App mode sync from user preferences ───────────────────────────────
  const persistedMode = user?.preferences?.default_app_mode;

  useEffect(() => {
    let mode: AppMode = "chat";
    if (isPaidEnterpriseFeaturesEnabled && searchUiEnabled && persistedMode) {
      mode = persistedMode.toLowerCase() as AppMode;
    }
    appModeRef.current = mode;
    setState({ phase: "idle", appMode: mode });
  }, [isPaidEnterpriseFeaturesEnabled, searchUiEnabled, persistedMode]);

  const setAppMode = useCallback(
    (mode: AppMode) => {
      if (!isPaidEnterpriseFeaturesEnabled || !searchUiEnabled) return;
      appModeRef.current = mode;
      setState((prev) =>
        prev.phase === "idle" ? { phase: "idle", appMode: mode } : prev
      );
    },
    [isPaidEnterpriseFeaturesEnabled, searchUiEnabled]
  );

  // ── Ancillary state ───────────────────────────────────────────────────
  const [query, setQuery] = useState<string | null>(null);
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
   * Perform document search (pure data-fetching, no phase side effects)
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
          throw err;
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

      const currentAppMode = appModeRef.current;

      // Always route through chat if:
      // 1. Not Enterprise Enabled
      // 2. Admin has disabled the Search UI
      // 3. Not in the "New Session" tab
      // 4. In "New Session" tab but app-mode is "Chat"
      if (
        !isPaidEnterpriseFeaturesEnabled ||
        !searchUiEnabled ||
        !appFocus.isNewSession() ||
        currentAppMode === "chat"
      ) {
        setState({ phase: "chat" });
        setSearchResults([]);
        setLlmSelectedDocIds(null);
        onChat(submitQuery);
        return;
      }

      // Search mode: immediately show SearchUI with loading state
      if (currentAppMode === "search") {
        setState({ phase: "searching" });
        try {
          await performSearch(submitQuery, filters);
        } catch (err) {
          if (err instanceof Error && err.name === "AbortError") return;
          throw err;
        }
        setState({ phase: "search-results" });
        appModeRef.current = "search";
        return;
      }

      // Auto mode: classify first, then route
      setState({ phase: "classifying" });
      try {
        const result = await performClassification(submitQuery);

        if (result === "search") {
          setState({ phase: "searching" });
          await performSearch(submitQuery, filters);
          setState({ phase: "search-results" });
          appModeRef.current = "search";
        } else {
          setState({ phase: "chat" });
          setSearchResults([]);
          setLlmSelectedDocIds(null);
          onChat(submitQuery);
        }
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          return;
        }

        setState({ phase: "chat" });
        setSearchResults([]);
        setLlmSelectedDocIds(null);
        onChat(submitQuery);
      }
    },
    [
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
      setState({ phase: "searching" });
      try {
        await performSearch(query, filters);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        throw err;
      }
      setState({ phase: "search-results" });
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
    setState({ phase: "idle", appMode: appModeRef.current });
    setSearchResults([]);
    setLlmSelectedDocIds(null);
    setError(null);
  }, []);

  const value: QueryControllerValue = useMemo(
    () => ({
      state,
      setAppMode,
      searchResults,
      llmSelectedDocIds,
      error,
      submit,
      refineSearch,
      reset,
    }),
    [
      state,
      setAppMode,
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
