// Chat-session search. Exposed as a mutation (per design doc 06) because the search
// is user-triggered/imperative rather than a declarative query.
//
// DEVIATION (documented): doc 06 specified "useMutation POST /search", but the real
// Onyx endpoint is `GET /api/chat/search?query=&page=&page_size=` returning
// ChatSearchResponse (backend/onyx/server/query_and_chat/chat_backend.py::search_chats).
// We keep the useMutation shape the doc asked for, but call the correct GET endpoint so
// it actually works against the live backend.
import { useMutation } from "@tanstack/react-query";
import { errorHandlingFetcher } from "@/lib/api";
import type { ChatSearchResponse } from "@/lib/types";
import { clientConfig } from "./client";

const DEFAULT_PAGE_SIZE = 10;

export interface SearchArgs {
  query?: string;
  page?: number;
  pageSize?: number;
}

function buildSearchUrl({ query, page, pageSize }: SearchArgs): string {
  const params = new URLSearchParams();
  if (query && query.trim()) params.set("query", query.trim());
  params.set("page", String(page ?? 1));
  params.set("page_size", String(pageSize ?? DEFAULT_PAGE_SIZE));
  return `/api/chat/search?${params.toString()}`;
}

export function useSearch() {
  return useMutation<ChatSearchResponse, Error, SearchArgs>({
    mutationFn: (args) =>
      errorHandlingFetcher<ChatSearchResponse>(
        buildSearchUrl(args),
        clientConfig
      ),
  });
}
