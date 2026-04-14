"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

export interface ImportJobStatus {
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
 *
 * If `importJobId` is provided, polls the specific job.
 * Otherwise, checks the `/import/active` endpoint once on mount to detect
 * an in-progress import (e.g. when the user navigates away and back).
 * Once a job ID is discovered, only the specific-job endpoint is polled.
 */
export function useImportStatus(rulesetId: string, importJobId: string | null) {
  // Tracks the job ID discovered via the /active endpoint so we can
  // stop polling /active once we know which job to watch.
  const [discoveredJobId, setDiscoveredJobId] = useState<string | null>(null);

  const needsDiscovery = !importJobId && !discoveredJobId;

  // One-shot fetch to discover an already-active import on mount
  const { data: activeJob } = useSWR<ImportJobStatus | null>(
    needsDiscovery
      ? `/api/proposal-review/rulesets/${rulesetId}/import/active`
      : null,
    errorHandlingFetcher
  );

  // Once the /active endpoint returns a job, capture its ID and stop polling /active
  useEffect(() => {
    if (activeJob?.id) {
      setDiscoveredJobId(activeJob.id);
    }
  }, [activeJob]);

  // Resolve which job ID to poll
  const resolvedJobId = importJobId ?? discoveredJobId;

  const { data, error } = useSWR<ImportJobStatus>(
    resolvedJobId
      ? `/api/proposal-review/rulesets/${rulesetId}/import/${resolvedJobId}/status`
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

  const job = data ?? null;

  return {
    importJob: job,
    isProcessing:
      !!job && (job.status === "PENDING" || job.status === "RUNNING"),
    isComplete: job?.status === "COMPLETED",
    isFailed: job?.status === "FAILED",
    error,
  };
}
