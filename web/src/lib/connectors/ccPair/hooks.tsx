"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import { toast } from "@opal/layouts";
import useSWRInfinite from "swr/infinite";
import { setCCPairStatus } from "@/lib/ccPair";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";
import type {
  CCPairFullInfo,
  CCPairRun,
  CCPairRunErrors,
  CCPairRef,
  CCPairRunsQuery,
  CCPairRunStatusGroup,
  IndexingRun,
} from "@/lib/connectors/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  resolveAllErrorsForCCPair,
  resolveErrors,
} from "@/lib/targeted_reindex";
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
// useActivityItems
// ---------------------------------------------------------------------------

/** Which list of an activity panel a run sits in. "other" is every run that neither failed nor has document errors. */
export type ActivityGroup = "failures" | "errors" | "other" | "resolved";

/** How each group narrows the runs feed. Resolved errors can sit on a run of any status. */
// A newer run of the same kind closes a failure, so only the latest failure
// per pair and kind stays live and the older ones join the resolved group.
const ACTIVITY_GROUP_QUERY = {
  failures: { statusGroups: ["failed"], errors: null, superseded: false },
  errors: {
    statusGroups: ["running", "succeeded", "canceled"],
    errors: "unresolved",
    superseded: null,
  },
  other: {
    statusGroups: ["running", "succeeded", "canceled"],
    errors: "none",
    superseded: null,
  },
  resolved: { statusGroups: null, errors: "resolved", superseded: true },
} satisfies Record<
  ActivityGroup,
  {
    statusGroups: CCPairRunStatusGroup[] | null;
    errors: CCPairRunErrors | null;
    superseded: boolean | null;
  }
>;

const ACTIVITY_PAGE_SIZE = 20;

/** Which pairs an activity feed reads: one pair, with whether the viewer may resolve its runs' document errors, or every readable one. */
export type ActivityScope = { ccPairId: number; canResolve: boolean } | "fleet";

/** One run in an activity panel, with the pair it ran on and what the viewer may do to it. */
export interface ActivityItem {
  ccPairId: number;
  run: CCPairRun;
  /** Set when the feed spans pairs, so the card names the pair. */
  connector: CCPairRef | undefined;
  /** The viewer may re-fetch single documents of the run's pair. */
  canResolve: boolean;
}

export interface ActivityGroupState {
  group: ActivityGroup;
  runs: ActivityItem[];
  /** Runs in the group, loaded or not. */
  total: number;
  loaded: boolean;
  failed: boolean;
  isLoading: boolean;
  /** Older runs than the pages loaded so far. */
  hasMore: boolean;
  more: () => void;
}

/** A page of either feed. A pair's feed returns bare runs, the fleet's wraps each with its pair. */
interface FeedPage {
  items: (CCPairRun | IndexingRun)[];
  total_items: number;
}

function itemOf(
  run: CCPairRun | IndexingRun,
  scope: ActivityScope
): ActivityItem {
  if ("cc_pair" in run) {
    return {
      ccPairId: run.cc_pair.id,
      run: run.run,
      connector: run.cc_pair,
      canResolve: run.cc_pair.can_resolve,
    };
  }
  // A bare run only comes from a pair's own feed.
  const pair = scope === "fleet" ? null : scope;
  if (pair === null)
    throw new Error("A fleet feed returned a run without its pair");
  return {
    ccPairId: pair.ccPairId,
    run,
    connector: undefined,
    canResolve: pair.canResolve,
  };
}

/** One activity group of the scope, polled while `enabled`. `more` loads the next page and a new search starts over. */
export function useActivityItems(
  scope: ActivityScope,
  group: ActivityGroup,
  q: string,
  enabled: boolean,
  pollMs: number
): ActivityGroupState {
  const ccPairId = scope === "fleet" ? null : scope.ccPairId;
  const canResolve = scope === "fleet" ? null : scope.canResolve;
  const { data, error, isLoading, size, setSize } = useSWRInfinite<FeedPage>(
    (pageIndex, previous: FeedPage | null) => {
      if (!enabled) return null;
      if (previous !== null && previous.items.length < ACTIVITY_PAGE_SIZE) {
        return null;
      }
      const groupQuery = ACTIVITY_GROUP_QUERY[group];
      const query: CCPairRunsQuery = {
        pageNum: pageIndex,
        pageSize: ACTIVITY_PAGE_SIZE,
        since: null,
        kinds: null,
        q,
        ...groupQuery,
        // A search finds old failures too, under the failures group.
        superseded: q ? null : groupQuery.superseded,
      };
      return ccPairId === null
        ? SWR_KEYS.indexMonitoringRuns(query)
        : SWR_KEYS.ccPairRuns(ccPairId, query);
    },
    errorHandlingFetcher,
    { refreshInterval: pollMs, keepPreviousData: true }
  );
  useEffect(() => {
    void setSize(1);
  }, [q, setSize]);
  // Polling shifts the offsets, so a run can land on two pages.
  const runs = useMemo(() => {
    const itemScope: ActivityScope =
      ccPairId === null || canResolve === null
        ? "fleet"
        : { ccPairId, canResolve };
    const seen = new Set<string>();
    return (data ?? []).flatMap((page) =>
      page.items
        .map((run) => itemOf(run, itemScope))
        .filter((item) => {
          const key = `${item.run.kind}-${item.run.attempt.id}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        })
    );
  }, [data, ccPairId, canResolve]);
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

// ---------------------------------------------------------------------------
// useResolveRunErrors
// ---------------------------------------------------------------------------

/** Resolves a run's document errors and refreshes every feed they appear in, one submit at a time. */
export function useResolveRunErrors() {
  const tToasts = useTranslations("admin.connector.toasts");
  const [resolving, setResolving] = useState(false);

  // Awaits only the submit. The feeds poll, so rows clear as documents land.
  async function resolve(item: ActivityItem, errorIds: number[] | null) {
    if (resolving) return;
    setResolving(true);
    try {
      const result =
        errorIds === null
          ? await resolveAllErrorsForCCPair(item.ccPairId, item.run.attempt.id)
          : await resolveErrors(errorIds);
      if (result.total_error_ids === 0) {
        toast.success(tToasts("noUnresolvedErrors"));
      } else {
        toast.success(
          tToasts("targetedReindexSubmitted", { count: result.total_error_ids })
        );
      }
      await mutate(
        (key) =>
          typeof key === "string" &&
          (key.startsWith(SWR_KEYS.ccPairIndexingErrors(item.ccPairId)) ||
            key.startsWith(SWR_KEYS.ccPairRunsPrefix(item.ccPairId)) ||
            key.startsWith(SWR_KEYS.indexMonitoringRunsPrefix))
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(tToasts("targetedReindexFailed", { message }));
    } finally {
      setResolving(false);
    }
  }

  return { resolving, resolve };
}
