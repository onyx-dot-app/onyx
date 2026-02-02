"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
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

export type QueryClassification = "search" | "chat" | null;

export interface QueryControllerContextValue {
  /** The query that was submitted */
  query: string | null;
  /** Classification state: null (idle), "search", or "chat" */
  classification: QueryClassification;
  /** Whether or not the currently submitted query is being actively classified by the backend */
  isClassifying: boolean;
  /** Search results (empty if chat or not yet searched) */
  searchResults: SearchDocWithContent[];
  /** Document IDs selected by the LLM as most relevant */
  llmSelectedDocIds: string[] | null;
  /** Submit a query - routes to search or chat based on app mode */
  submit: (query: string, filters?: BaseFilters) => Promise<void>;
  /** Re-run the current search query with updated server-side filters */
  refineSearch: (filters: BaseFilters) => Promise<void>;
  /** Reset all state to initial values */
  reset: () => void;
  /** Register the onChat callback (called from AppPage) */
  registerOnChat: (cb: (query: string) => void) => void;
}

const QueryControllerContext =
  createContext<QueryControllerContextValue | null>(null);

export function useQueryControllerContext(): QueryControllerContextValue {
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

  // onChat callback ref — set by the consumer via registerOnChat
  const onChatRef = useRef<((query: string) => void) | null>(null);

  const registerOnChat = useCallback((cb: (query: string) => void) => {
    onChatRef.current = cb;
  }, []);

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
    async (submitQuery: string, filters?: BaseFilters): Promise<void> => {
      setQuery(submitQuery);

      const onChat = onChatRef.current;

      if (!appFocus.isNewSession()) {
        setSearchResults([]);
        setLlmSelectedDocIds(null);
        onChat?.(submitQuery);
        return;
      }

      if (appMode === "chat") {
        setClassification("chat");
        setSearchResults([]);
        setLlmSelectedDocIds(null);
        onChat?.(submitQuery);
        return;
      }

      if (appMode === "search") {
        await performSearch(submitQuery, filters);
        setClassification("search");
        return;
      }

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
          onChat?.(submitQuery);
        }
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          return;
        }

        setClassification("chat");
        setSearchResults([]);
        setLlmSelectedDocIds(null);
        onChat?.(submitQuery);
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

  // Sync classification state with navigation context
  const appFocusType = appFocus.getType();
  const appFocusId = appFocus.getId();
  useEffect(() => {
    if (appFocusType === "chat") setClassification("chat");
    else reset();
  }, [appFocusType, appFocusId, reset]);

  const value: QueryControllerContextValue = {
    query,
    classification,
    isClassifying,
    searchResults,
    llmSelectedDocIds,
    submit,
    refineSearch,
    reset,
    registerOnChat,
  };

  return (
    <QueryControllerContext.Provider value={value}>
      {children}
    </QueryControllerContext.Provider>
  );
}
