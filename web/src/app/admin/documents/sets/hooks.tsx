import { errorHandlingFetcher } from "@/lib/fetcher";
import { DocumentSet } from "@/lib/types";
import useSWR, { mutate } from "swr";

const DOCUMENT_SETS_URL = "/api/manage/admin/document-set";

export function refreshDocumentSets() {
  mutate(DOCUMENT_SETS_URL);
}

export function useDocumentSets() {
  const swrResponse = useSWR<DocumentSet[]>(
    DOCUMENT_SETS_URL,
    errorHandlingFetcher,
    {
      refreshInterval: 5000, // 5 seconds
    }
  );

  return {
    ...swrResponse,
    refreshDocumentSets: refreshDocumentSets,
  };
}
