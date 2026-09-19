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
    // Fast poll while a set is syncing, slow background poll otherwise so we
    // still pick up syncs kicked off in another admin tab without hammering
    // the endpoint at 5 s intervals when nothing is happening.
    refreshInterval: (data) =>
      data && data.some((ds) => !ds.is_up_to_date) ? 5000 : 30000,
  });

  return {
    ...swrResponse,
    refreshDocumentSets: refreshDocumentSets,
  };
}
