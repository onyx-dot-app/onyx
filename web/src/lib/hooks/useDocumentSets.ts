import useSWR from "swr";
import { DocumentSetSummary } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

export function useDocumentSets() {
  const { data, error, mutate } = useSWR<DocumentSetSummary[]>(
    SWR_KEYS.documentSets,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  return {
    documentSets: data ?? [],
    isLoading: !error && !data,
    error,
    refresh: mutate,
  };
}
