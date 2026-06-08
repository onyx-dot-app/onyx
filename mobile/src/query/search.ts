// A mutation (not a query) because search is user-triggered. Backs onto the
// GET /api/chat/search endpoint despite the useMutation shape.
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
