"use client";

import useSWR, { type SWRResponse } from "swr";
import { errorHandlingFetcher, type FetchError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

export interface DocumentContent {
  title: string;
  content: string;
  link: string | null;
}

export function useDocumentContent(
  documentId: string | null
): SWRResponse<DocumentContent, FetchError> {
  return useSWR<DocumentContent, FetchError>(
    documentId ? SWR_KEYS.documentContent(documentId) : null,
    errorHandlingFetcher,
    { shouldRetryOnError: false }
  );
}
