"use client";

import { useEffect } from "react";
import useSWR from "swr";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { IndexAttemptStageMetricsResponse } from "@/lib/types";

/**
 * Fetches the per-stage timing metrics recorded for a single index attempt.
 *
 * The backend records both per-batch (`BATCH_LEVEL`) and per-attempt
 * (`ATTEMPT_LEVEL`) stage durations during indexing. This hook surfaces them
 * for the admin UI's stage details popover. SWR cache key comes from
 * `SWR_KEYS.indexAttemptStageMetrics`.
 *
 * Disables `revalidateOnFocus` since stage metrics are only written when an
 * attempt completes a batch, and skips retries on auth errors to avoid
 * spamming the endpoint when an admin's session has expired.
 */
export default function useIndexAttemptStageMetrics(indexAttemptId: number) {
  const { data, error } = useSWR<IndexAttemptStageMetricsResponse>(
    SWR_KEYS.indexAttemptStageMetrics(indexAttemptId),
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      onErrorRetry: skipRetryOnAuthError,
    }
  );

  // The popover shows a generic load error, so log the payload for debugging.
  useEffect(() => {
    if (error) {
      console.error(
        `Failed to load stage metrics for index attempt ${indexAttemptId}:`,
        error
      );
    }
  }, [error, indexAttemptId]);

  return { data, error };
}
