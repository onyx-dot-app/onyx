"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { ReviewRun } from "@/app/proposal-review/types";

/**
 * Polls the review status endpoint every 2.5 seconds while a review is running.
 * Stops polling once the status is COMPLETED or FAILED.
 *
 * The backend returns a full ReviewRunResponse (mapped to ReviewRun on the
 * frontend). Only a subset of fields (status, total_rules, completed_rules)
 * is typically consumed by callers.
 */
export function useReviewStatus(
  proposalId: string | null,
  isReviewRunning: boolean
) {
  const { data, error, isLoading } = useSWR<ReviewRun>(
    proposalId && isReviewRunning
      ? `/api/proposal-review/proposals/${proposalId}/review-status`
      : null,
    errorHandlingFetcher,
    {
      refreshInterval: isReviewRunning ? 2500 : 0,
      revalidateOnFocus: false,
    }
  );

  return {
    reviewStatus: data ?? null,
    error,
    isLoading,
  };
}
