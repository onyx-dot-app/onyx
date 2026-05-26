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
    // Only poll while at least one document set is still syncing. Steady-state
    // admins keep this page open without re-fetching every 5 s.
    refreshInterval: (data) =>
      data && data.some((ds) => !ds.is_up_to_date) ? 5000 : 0,
  });

  return {
    ...swrResponse,
    refreshDocumentSets: refreshDocumentSets,
  };
}
