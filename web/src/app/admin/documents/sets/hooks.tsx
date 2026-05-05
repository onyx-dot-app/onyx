import { errorHandlingFetcher } from "@/lib/fetcher";
import { DocumentSetSummary } from "@/lib/types";
import useSWR, { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

export function refreshDocumentSets() {
  mutate(SWR_KEYS.documentSets);
}

export function useDocumentSets(getEditable: boolean = false) {
  const url = getEditable
    ? SWR_KEYS.documentSetsEditable
    : SWR_KEYS.documentSets;

  const swrResponse = useSWR<DocumentSetSummary[]>(url, errorHandlingFetcher, {
    refreshInterval: 5000, // 5 seconds
  });

  return {
    ...swrResponse,
    refreshDocumentSets: refreshDocumentSets,
  };
}
