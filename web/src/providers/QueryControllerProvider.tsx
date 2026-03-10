"use client";

import { createContext, useContext } from "react";
import { eeGated } from "@/ce";
import { QueryControllerProvider as EEQueryControllerProvider } from "@/ee/providers/QueryControllerProvider";
import { SearchDocWithContent, BaseFilters } from "@/lib/search/interfaces";

export type AppMode = "auto" | "search" | "chat";

export type QueryPhase =
  | "idle" // no query submitted; WelcomeMessage visible, mode toggle visible
  | "classifying" // auto mode: LLM deciding search vs chat
  | "searching" // search request in-flight; SearchUI mounted with loading skeleton
  | "search-results" // search complete; SearchUI showing results
  | "chat"; // routed to chat; QueryController is done

export interface QueryControllerValue {
  /** User-selected app mode (search / chat / auto). Controls how the next query is routed. */
  appMode: AppMode;
  /** Update the app mode. No-op in CE or when search is unavailable. */
  setAppMode: (mode: AppMode) => void;
  /** Current phase of the query lifecycle */
  phase: QueryPhase;
  /** Search results (empty if chat or not yet searched) */
  searchResults: SearchDocWithContent[];
  /** Document IDs selected by the LLM as most relevant */
  llmSelectedDocIds: string[] | null;
  /** User-facing error message from the last search or classification request, null when idle */
  error: string | null;
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

export const QueryControllerContext = createContext<QueryControllerValue>({
  appMode: "chat",
  setAppMode: () => undefined,
  phase: "idle",
  searchResults: [],
  llmSelectedDocIds: null,
  error: null,
  submit: async (_q, onChat) => {
    onChat(_q);
  },
  refineSearch: async () => undefined,
  reset: () => undefined,
});

export function useQueryController(): QueryControllerValue {
  return useContext(QueryControllerContext);
}

export const QueryControllerProvider = eeGated(EEQueryControllerProvider);
