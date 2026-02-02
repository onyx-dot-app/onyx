"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  useMemo,
} from "react";
import {
  BaseFilters,
  classifyQuery,
  SearchDocWithContent,
  searchDocuments,
  SearchFlowClassificationResponse,
  SearchFullResponse,
} from "@/lib/search/searchApi";
import { useAppMode } from "@/providers/AppModeProvider";
import useAppFocus from "@/hooks/useAppFocus";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";

export type QueryClassification = "search" | "chat" | null;

export interface QueryControllerValue {
  /** Classification state: null (idle), "search", or "chat" */
  classification: QueryClassification;
  /** Whether or not the currently submitted query is being actively classified by the backend */
  isClassifying: boolean;
  /** Search results (empty if chat or not yet searched) */
  searchResults: SearchDocWithContent[];
  /** Document IDs selected by the LLM as most relevant */
  llmSelectedDocIds: string[] | null;
  /** Submit a query - routes to search or chat based on app mode */
  submit: (
    query: string,
    onChat: (query: string) => void,
    filters?: BaseFilters
  ) => Promise<void>;
  /** Re-run the current search query with updated server-side filters */
  refineSearch: (filters: BaseFilters) => Promise<void>;
  /** Reset all state to initial values */
  reset: () => void;
}

const QueryControllerContext = createContext<QueryControllerValue | null>(null);

export function useQueryController(): QueryControllerValue {
  const ctx = useContext(QueryControllerContext);
  if (!ctx) {
    throw new Error(
      "useQueryControllerContext must be used within a QueryControllerProvider"
    );
  }
  return ctx;
}

interface QueryControllerProviderProps {
  children: React.ReactNode;
}

export function QueryControllerProvider({
  children,
}: QueryControllerProviderProps) {
  const { appMode } = useAppMode();
  const appFocus = useAppFocus();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

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
            numHits: 50,
            includeContent: false,
            signal: controller.signal,
          }
        );

        if (response.error) {
          setSearchResults([]);
          setLlmSelectedDocIds(null);
          return;
        }

        setSearchResults(response.search_docs);
        setLlmSelectedDocIds(response.llm_selected_doc_ids ?? null);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") {
          return;
        }

        console.error("Document search failed:", err);
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

        console.error("Query classification failed:", error);
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

      // 1.
      // We always route through chat if we're not Enterprise Enabled.
      //
      // 2.
      // We only go down the classification route if we're in the "New Session" tab.
      // Everywhere else, we always use the chat-flow.
      //
      // 3.
      // If we're in the "New Session" tab and the app-mode is "Chat", we continue with the chat-flow anyways.
      if (
        !isPaidEnterpriseFeaturesEnabled ||
        !appFocus.isNewSession() ||
        appMode === "chat"
      ) {
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
    [appMode, appFocus, performClassification, performSearch]
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
  }, []);

  const value: QueryControllerValue = useMemo(
    () => ({
      classification,
      isClassifying,
      searchResults,
      llmSelectedDocIds,
      submit,
      refineSearch,
      reset,
    }),
    [
      classification,
      isClassifying,
      searchResults,
      llmSelectedDocIds,
      submit,
      refineSearch,
      reset,
    ]
  );

  // Sync classification state with navigation context
  useEffect(() => {
    if (appFocus.isNewSession()) return;
    reset();
  }, [appFocus, reset]);

  return (
    <QueryControllerContext.Provider value={value}>
      {children}
    </QueryControllerContext.Provider>
  );
}
