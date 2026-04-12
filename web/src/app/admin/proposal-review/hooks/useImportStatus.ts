"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface ImportJobStatus {
  id: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
  source_filename: string;
  rules_created: number;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

/**
 * Polls an import job's status endpoint while the job is active.
 * Stops polling once the job reaches a terminal state (COMPLETED or FAILED).
 */
export function useImportStatus(rulesetId: string, importJobId: string | null) {
  const isActive = importJobId !== null;

  const { data, error } = useSWR<ImportJobStatus>(
    isActive
      ? `/api/proposal-review/rulesets/${rulesetId}/import/${importJobId}/status`
      : null,
    errorHandlingFetcher,
    {
      refreshInterval: (latestData) => {
        if (!latestData) return 5000;
        if (
          latestData.status === "COMPLETED" ||
          latestData.status === "FAILED"
        ) {
          return 0; // stop polling
        }
        return 5000;
      },
    }
  );

  return {
    importJob: data ?? null,
    isProcessing:
      isActive &&
      (!data || data.status === "PENDING" || data.status === "RUNNING"),
    isComplete: data?.status === "COMPLETED",
    isFailed: data?.status === "FAILED",
    error,
  };
}
