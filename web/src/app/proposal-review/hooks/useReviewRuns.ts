"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { ReviewRun } from "@/app/proposal-review/types";

/**
 * Fetches the list of review runs for a proposal, most recent first.
 * Revalidates when `refreshKey` changes (e.g. after triggering a new run).
 */
export function useReviewRuns(proposalId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<ReviewRun[]>(
    proposalId
      ? `/api/proposal-review/proposals/${proposalId}/review-runs`
      : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return {
    runs: data ?? [],
    error,
    isLoading,
    mutate,
  };
}
