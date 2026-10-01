"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { CCPairManageAccessRow } from "@/lib/connectors/manageAccess/types";

/**
 * The groups that manage a cc-pair: fixed rows (global Manage Connectors
 * grants) first, then the stored rows of groups the caller can see. The
 * server answers only callers who can operate the pair, so pass
 * `enabled: false` otherwise.
 */
export function useCCPairManageAccess(ccPairId: number, enabled: boolean) {
  return useSWR<CCPairManageAccessRow[], Error>(
    enabled ? SWR_KEYS.ccPairManageAccess(ccPairId) : null,
    errorHandlingFetcher
  );
}
