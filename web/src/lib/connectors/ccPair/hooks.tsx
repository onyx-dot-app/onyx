"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import useSWRInfinite from "swr/infinite";
import { setCCPairStatus } from "@/lib/ccPair";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";
import type {
  CCPairFullInfo,
  CCPairRun,
  CCPairRunErrors,
  CCPairRunsQuery,
  CCPairRunStatusGroup,
  IndexingRun,
} from "@/lib/connectors/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";

// ---------------------------------------------------------------------------
// useStatusChange
// ---------------------------------------------------------------------------

/** Pauses, resumes, or re-enables a cc-pair, confirming first when it is invalid. */
export function useStatusChange(ccPair: CCPairFullInfo | null) {
  const t = useTranslations("admin.connector");
  const [isUpdating, setIsUpdating] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);

  const updateStatus = async (newStatus: ConnectorCredentialPairStatus) => {
    if (!ccPair) return false;

    setIsUpdating(true);

    try {
      // Call the backend to update the status
      await setCCPairStatus(ccPair.id, newStatus);

      // Use mutate to revalidate the status on the backend
      await mutate(buildCCPairInfoUrl(ccPair.id));
    } catch (error) {
      console.error("Failed to update status", error);
    } finally {
      // Reset local updating state and button text after mutation
      setIsUpdating(false);
    }

    return true;
  };

  const handleStatusChange = async (
    newStatus: ConnectorCredentialPairStatus
  ) => {
    if (isUpdating || !ccPair) return false; // Prevent double-clicks or multiple requests

    if (
      ccPair.status === ConnectorCredentialPairStatus.INVALID &&
      newStatus === ConnectorCredentialPairStatus.ACTIVE
    ) {
      setShowConfirmModal(true);
      return false;
    } else {
      return await updateStatus(newStatus);
    }
  };

  const ConfirmModal =
    showConfirmModal && ccPair ? (
      <ConfirmEntityModal
        entityType={t("reEnableModal.entityType")}
        entityName={ccPair.name}
        onClose={() => setShowConfirmModal(false)}
        onSubmit={() => {
          setShowConfirmModal(false);
          updateStatus(ConnectorCredentialPairStatus.ACTIVE);
        }}
        additionalDetails={t("reEnableModal.additionalDetails")}
        actionButtonText={t("reEnableModal.actionButton.label")}
      />
    ) : null;

  return {
    handleStatusChange,
    isUpdating,
    ConfirmModal,
  };
}

// ---------------------------------------------------------------------------
// useActivityGroup
// ---------------------------------------------------------------------------

/** Which list of the connector page's activity panel a run sits in. */
export type ActivityGroup = "failures" | "errors" | "resolved";

/** How each group narrows the runs feed. Resolved errors can sit on a run of any status. */
const ACTIVITY_GROUP_QUERY: Record<
  ActivityGroup,
  {
    statusGroups: CCPairRunStatusGroup[] | null;
    errors: CCPairRunErrors | null;
  }
> = {
  failures: { statusGroups: ["failed"], errors: null },
  errors: {
    statusGroups: ["running", "succeeded", "canceled"],
    errors: "unresolved",
  },
  resolved: { statusGroups: null, errors: "resolved" },
};

const ACTIVITY_PAGE_SIZE = 20;

/** Which pairs an activity feed reads: one pair, or every readable one. */
export type ActivityScope = { ccPairId: number } | "fleet";

export interface ActivityGroupState<Run> {
  group: ActivityGroup;
  runs: Run[];
  /** Runs in the group, loaded or not. */
  total: number;
  loaded: boolean;
  failed: boolean;
  isLoading: boolean;
  /** Older runs than the pages loaded so far. */
  hasMore: boolean;
  more: () => void;
}

interface RunsPage<Run> {
  items: Run[];
  total_items: number;
}

/** Pages one feed query, polled while `enabled`. `more` loads the next page; a new search starts over. */
function usePagedRuns<Run>(
  keyFor: (query: CCPairRunsQuery) => string,
  runKey: (run: Run) => string,
  group: ActivityGroup,
  q: string,
  enabled: boolean,
  pollMs: number
): ActivityGroupState<Run> {
  const { data, error, isLoading, size, setSize } = useSWRInfinite<
    RunsPage<Run>
  >(
    (pageIndex, previous: RunsPage<Run> | null) => {
      if (!enabled) return null;
      if (previous !== null && previous.items.length < ACTIVITY_PAGE_SIZE) {
        return null;
      }
      return keyFor({
        pageNum: pageIndex,
        pageSize: ACTIVITY_PAGE_SIZE,
        since: null,
        kinds: null,
        q,
        ...ACTIVITY_GROUP_QUERY[group],
      });
    },
    errorHandlingFetcher,
    { refreshInterval: pollMs, keepPreviousData: true }
  );
  useEffect(() => {
    void setSize(1);
  }, [q, setSize]);
  // Polling shifts the offsets, so a run can land on two pages.
  const runs = useMemo(() => {
    const seen = new Set<string>();
    return (data ?? []).flatMap((page) =>
      page.items.filter((run) => {
        const key = runKey(run);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
    );
  }, [data, runKey]);
  const first = data?.[0];
  const last = data?.[data.length - 1];
  return {
    group,
    runs,
    total: first?.total_items ?? 0,
    loaded: first !== undefined,
    failed: error !== undefined,
    isLoading,
    hasMore:
      first !== undefined &&
      last !== undefined &&
      runs.length < first.total_items &&
      last.items.length === ACTIVITY_PAGE_SIZE,
    more: () => void setSize(size + 1),
  };
}

function ccPairRunKey(run: CCPairRun): string {
  return `${run.kind}-${run.attempt.id}`;
}

function indexingRunKey(item: IndexingRun): string {
  return ccPairRunKey(item.run);
}

/** One activity group of a pair. */
export function useActivityGroup(
  ccPairId: number,
  group: ActivityGroup,
  q: string,
  enabled: boolean,
  pollMs: number
): ActivityGroupState<CCPairRun> {
  const keyFor = useCallback(
    (query: CCPairRunsQuery) => SWR_KEYS.ccPairRuns(ccPairId, query),
    [ccPairId]
  );
  return usePagedRuns<CCPairRun>(
    keyFor,
    ccPairRunKey,
    group,
    q,
    enabled,
    pollMs
  );
}

/** One activity group across every readable pair. Each run names its pair. */
export function useFleetActivityGroup(
  group: ActivityGroup,
  q: string,
  enabled: boolean,
  pollMs: number
): ActivityGroupState<IndexingRun> {
  return usePagedRuns<IndexingRun>(
    SWR_KEYS.indexMonitoringRuns,
    indexingRunKey,
    group,
    q,
    enabled,
    pollMs
  );
}
