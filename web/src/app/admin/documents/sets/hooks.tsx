import { errorHandlingFetcher } from "@/lib/fetcher";
import { DocumentSetSummary } from "@/lib/types";
import useSWR, { mutate } from "swr";

const DOCUMENT_SETS_URL = "/api/manage/document-set";
const GET_EDITABLE_DOCUMENT_SETS_URL =
  "/api/manage/document-set?get_editable=true";

export function refreshDocumentSets() {
  mutate(DOCUMENT_SETS_URL);
}

export function useDocumentSets(getEditable: boolean = false) {
  const url = getEditable ? GET_EDITABLE_DOCUMENT_SETS_URL : DOCUMENT_SETS_URL;

  const swrResponse = useSWR<DocumentSetSummary[]>(url, errorHandlingFetcher, {
    refreshInterval: 5000, // 5 seconds
  });

  return {
    ...swrResponse,
    refreshDocumentSets: refreshDocumentSets,
  };
}
