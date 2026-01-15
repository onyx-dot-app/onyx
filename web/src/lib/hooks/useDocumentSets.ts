import useSWR from "swr";
import { DocumentSetSummary } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useDocumentSets() {
  const { data, error, mutate } = useSWR<DocumentSetSummary[]>(
    "/api/manage/document-set",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
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
