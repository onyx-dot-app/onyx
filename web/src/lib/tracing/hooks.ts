"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { TracingProviderView } from "@/lib/tracing/types";

export function useTracingProviders() {
  const { data, error, isLoading, mutate } = useSWR<TracingProviderView[]>(
    SWR_KEYS.tracingProviders,
    errorHandlingFetcher
  );
  return {
    providers: data ?? [],
    error,
    isLoading,
    mutateProviders: mutate,
  };
}
