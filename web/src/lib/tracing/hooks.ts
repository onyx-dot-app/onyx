"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { TracingProviderView } from "@/lib/tracing/types";

export const TRACING_PROVIDERS_URL = "/api/admin/tracing/providers";

export function useTracingProviders() {
  const { data, error, isLoading, mutate } = useSWR<TracingProviderView[]>(
    TRACING_PROVIDERS_URL,
    errorHandlingFetcher
  );
  return {
    providers: data ?? [],
    error,
    isLoading,
    mutateProviders: mutate,
  };
}
