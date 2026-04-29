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
 * for the admin UI's stage metrics panel. SWR cache key comes from
 * `SWR_KEYS.indexAttemptStageMetrics`.
 *
 * Disables `revalidateOnFocus` since stage metrics are only written when an
 * attempt completes a batch, and skips retries on auth errors to avoid
 * spamming the endpoint when an admin's session has expired.
 *
 * @returns Object containing:
 *   - data: `IndexAttemptStageMetricsResponse` or `undefined` while loading
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Error object if the fetch failed
 *   - mutate: Function to manually revalidate
 */
export default function useIndexAttemptStageMetrics(indexAttemptId: number) {
  const { data, error, isLoading, mutate } =
    useSWR<IndexAttemptStageMetricsResponse>(
      SWR_KEYS.indexAttemptStageMetrics(indexAttemptId),
      errorHandlingFetcher,
      {
        revalidateOnFocus: false,
        onErrorRetry: skipRetryOnAuthError,
      }
    );

  // Surface the underlying error in the console so debugging doesn't require
  // digging into the Network tab — the visible MessageCard intentionally hides
  // upstream payload details from admins.
  useEffect(() => {
    if (error) {
      console.error(
        `Failed to load stage metrics for index attempt ${indexAttemptId}:`,
        error
      );
    }
  }, [error, indexAttemptId]);

  return {
    data,
    isLoading,
    error,
    mutate,
  };
}
