import useSWR from "swr";
import { DocumentSetSummary } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

/** `enabled: false` skips the request and reports not loading. */
export function useDocumentSets(enabled: boolean = true) {
  const { data, error, mutate } = useSWR<DocumentSetSummary[]>(
    enabled ? SWR_KEYS.documentSets : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  return {
    documentSets: data ?? [],
    isLoading: enabled && !error && !data,
    error,
    refresh: mutate,
  };
}
