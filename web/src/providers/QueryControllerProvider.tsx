"use client";

import { createContext, useContext } from "react";
import { eeGated } from "@/ce";
import { QueryControllerProvider as EEQueryControllerProvider } from "@/ee/providers/QueryControllerProvider";
import { SearchDocWithContent, BaseFilters } from "@/lib/search/interfaces";

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
  classification: null,
  isClassifying: false,
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
