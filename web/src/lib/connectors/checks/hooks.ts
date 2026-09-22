"use client";

import { useCallback, useState } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  capabilityReportUrl,
  runCapabilityCheck,
} from "@/lib/connectors/checks/svc";
import type { CapabilityReportSnapshot } from "@/lib/connectors/checks/types";

const RUNNING_POLL_INTERVAL_MS = 2000;

export interface UseCapabilityReportResult {
  /** `null` when no run has ever been stored for this scope. */
  snapshot: CapabilityReportSnapshot | null | undefined;
  isLoading: boolean;
  error: unknown;
  /** True from the re-run request until the row reads `completed`. */
  running: boolean;
  rerun: () => Promise<void>;
}

/**
 * The latest capability report for a credential, scoped to a connector when
 * given. Polls while a run is in flight so the card settles on its own.
 */
export function useCapabilityReport(
  credentialId: number,
  connectorId?: number | null
): UseCapabilityReportResult {
  const [requesting, setRequesting] = useState(false);
  const { data, error, isLoading, mutate } =
    useSWR<CapabilityReportSnapshot | null>(
      capabilityReportUrl(credentialId, connectorId),
      errorHandlingFetcher,
      {
        refreshInterval: (latest) =>
          latest?.run_status === "running" ? RUNNING_POLL_INTERVAL_MS : 0,
      }
    );

  const rerun = useCallback(async () => {
    setRequesting(true);
    try {
      const accepted = await runCapabilityCheck(credentialId, connectorId);
      // Seed the running row so polling starts before the next fetch.
      await mutate(accepted, { revalidate: false });
    } finally {
      setRequesting(false);
    }
  }, [credentialId, connectorId, mutate]);

  return {
    snapshot: data,
    isLoading,
    error,
    running: requesting || data?.run_status === "running",
    rerun,
  };
}
