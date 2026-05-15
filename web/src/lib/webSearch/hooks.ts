"use client";

import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type {
  WebSearchProviderView,
  WebContentProviderView,
} from "@/lib/webSearch/types";

export function useWebSearchProviders() {
  const {
    data: searchProvidersData,
    error: searchProvidersError,
    isLoading: isLoadingSearch,
    mutate: mutateSearchProviders,
  } = useSWR<WebSearchProviderView[]>(
    SWR_KEYS.webSearchSearchProviders,
    errorHandlingFetcher
  );

  const {
    data: contentProvidersData,
    error: contentProvidersError,
    isLoading: isLoadingContent,
    mutate: mutateContentProviders,
  } = useSWR<WebContentProviderView[]>(
    SWR_KEYS.webSearchContentProviders,
    errorHandlingFetcher
  );

  return {
    searchProviders: searchProvidersData ?? [],
    contentProviders: contentProvidersData ?? [],
    searchProvidersError,
    contentProvidersError,
    isLoading: isLoadingSearch || isLoadingContent,
    mutateSearchProviders,
    mutateContentProviders,
  };
}
