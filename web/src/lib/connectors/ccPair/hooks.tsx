"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import { toast } from "@opal/layouts";
import useSWRInfinite from "swr/infinite";
import {
  resolveCCPairRuns,
  resolveMatchingRuns,
  setCCPairStatus,
} from "@/lib/ccPair";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";
import type {
  CCPairFullInfo,
  CCPairRun,
  CCPairRunErrors,
  CCPairRef,
  CCPairRunLevel,
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

/** Which level of an activity panel a run sits in. "other" is every run that neither failed nor has document errors. */
export type ActivityGroup = "failures" | "errors" | "other";

interface ActivityGroupQuery {
  statusGroups: CCPairRunStatusGroup[] | null;
  errors: CCPairRunErrors | null;
  superseded: boolean | null;
  resolved: boolean | null;
}

const NOT_FAILED: CCPairRunStatusGroup[] = ["running", "succeeded", "canceled"];

/** How each level narrows the runs feed, for its open runs and its closed ones. */
// A closed failure was resolved or followed by a newer run of its kind. A
// closed error run was resolved or had all its document errors resolved.
// Nothing in "other" is open, so it has no closed runs.
const ACTIVITY_GROUP_QUERY = {
  failures: {
    open: {
      statusGroups: ["failed"],
      errors: null,
      superseded: false,
      resolved: false,
    },
    closed: {
      statusGroups: ["failed"],
      errors: null,
      superseded: true,
      resolved: true,
    },
  },
  errors: {
    open: {
      statusGroups: NOT_FAILED,
      errors: "unresolved",
      superseded: null,
      resolved: false,
    },
    closed: {
      statusGroups: NOT_FAILED,
      errors: "resolved",
      superseded: null,
      resolved: true,
    },
  },
  other: {
    open: {
      statusGroups: NOT_FAILED,
      errors: "none",
      superseded: null,
      resolved: null,
    },
    closed: null,
  },
} satisfies Record<
  ActivityGroup,
  { open: ActivityGroupQuery; closed: ActivityGroupQuery | null }
>;

const ACTIVITY_PAGE_SIZE = 20;

/** Which pairs an activity feed reads: one pair, with what the viewer may resolve on it, or every readable one. */
export type ActivityScope =
  | { ccPairId: number; canResolve: boolean; canResolveRuns: boolean }
  | "fleet";

/** One run in an activity panel, with the pair it ran on and what the viewer may do to it. */
export interface ActivityItem {
  ccPairId: number;
  run: CCPairRun;
  /** Set when the feed spans pairs, so the card names the pair. */
  connector: CCPairRef | undefined;
  /** The viewer may re-fetch single documents of the run's pair. */
  canResolve: boolean;
  /** The viewer may mark the run resolved. */
  canResolveRuns: boolean;
}

export interface ActivityGroupState {
  group: ActivityGroup;
  /** Lists the level's resolved and superseded runs rather than its open ones. */
  closed: boolean;
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
      canResolveRuns: run.cc_pair.can_resolve_runs,
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
    canResolveRuns: pair.canResolveRuns,
  };
}

/** One activity level of the scope, its open runs or its `closed` ones, polled while `enabled`. `more` loads the next page and a new search starts over. */
export function useActivityItems(
  scope: ActivityScope,
  group: ActivityGroup,
  closed: boolean,
  q: string,
  enabled: boolean,
  pollMs: number
): ActivityGroupState {
  const ccPairId = scope === "fleet" ? null : scope.ccPairId;
  const pair = scope === "fleet" ? null : scope;
  // Primitives, so a scope rebuilt every render does not remap the runs.
  const canResolve = pair?.canResolve ?? null;
  const canResolveRuns = pair?.canResolveRuns ?? null;
  const groupQuery = ACTIVITY_GROUP_QUERY[group][closed ? "closed" : "open"];
  const { data, error, isLoading, size, setSize } = useSWRInfinite<FeedPage>(
    (pageIndex, previous: FeedPage | null) => {
      if (!enabled || groupQuery === null) return null;
      if (previous !== null && previous.items.length < ACTIVITY_PAGE_SIZE) {
        return null;
      }
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
      ccPairId === null || canResolve === null || canResolveRuns === null
        ? "fleet"
        : { ccPairId, canResolve, canResolveRuns };
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
  }, [data, ccPairId, canResolve, canResolveRuns]);
  const first = data?.[0];
  const last = data?.[data.length - 1];
  return {
    group,
    closed,
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

/** Refetches the fleet feed and the given pairs' feeds. */
function refreshFeeds(ccPairIds: number[]) {
  const prefixes = [
    SWR_KEYS.indexMonitoringRunsPrefix,
    SWR_KEYS.indexMonitoringResolvableRunsCountPrefix,
    ...ccPairIds.flatMap((ccPairId) => [
      SWR_KEYS.ccPairIndexingErrors(ccPairId),
      SWR_KEYS.ccPairRunsPrefix(ccPairId),
      SWR_KEYS.ccPairResolvableRunsCountPrefix(ccPairId),
    ]),
  ];
  return mutate(
    (key) =>
      typeof key === "string" &&
      prefixes.some((prefix) => key.startsWith(prefix))
  );
}

/** How many open runs of the level the batch resolve would mark for the search, on the pair or the pairs the caller operates. Null skips the fetch. */
export function useResolvableRunsCount(
  scope: ActivityScope,
  level: CCPairRunLevel | null,
  q: string,
  pollMs: number
): { count: number; isLoading: boolean } {
  const ccPairId = scope === "fleet" ? null : scope.ccPairId;
  const { data, isLoading } = useSWR<{ count: number }>(
    level === null
      ? null
      : ccPairId === null
        ? SWR_KEYS.indexMonitoringResolvableRunsCount(level, q)
        : SWR_KEYS.ccPairResolvableRunsCount(ccPairId, level, q),
    errorHandlingFetcher,
    { refreshInterval: pollMs, keepPreviousData: true }
  );
  return { count: data?.count ?? 0, isLoading };
}

// ---------------------------------------------------------------------------
// useResolveRunErrors
// ---------------------------------------------------------------------------

/** Resolves a run's document errors by a targeted reindex, or marks the run resolved, and refreshes every feed it appears in, one submit at a time. */
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
      await refreshFeeds([item.ccPairId]);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(tToasts("targetedReindexFailed", { message }));
    } finally {
      setResolving(false);
    }
  }

  // Marks the run resolved without re-fetching anything: it keeps its status.
  async function resolveRun(item: ActivityItem) {
    if (resolving) return;
    setResolving(true);
    try {
      await resolveCCPairRuns(item.ccPairId, [
        { kind: item.run.kind, attempt_id: item.run.attempt.id },
      ]);
      toast.success(tToasts("runResolved"));
      await refreshFeeds([item.ccPairId]);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(tToasts("runResolveFailed", { message }));
    } finally {
      setResolving(false);
    }
  }

  // Marks every open run of the level the panel lists for the search resolved.
  async function resolveMatching(
    scope: ActivityScope,
    level: CCPairRunLevel,
    q: string
  ) {
    if (resolving) return;
    setResolving(true);
    const ccPairId = scope === "fleet" ? null : scope.ccPairId;
    try {
      const result = await resolveMatchingRuns(ccPairId, {
        level,
        q: q || null,
        since: null,
        kinds: null,
      });
      toast.success(tToasts("runsResolved", { count: result.resolved_count }));
      await refreshFeeds(ccPairId === null ? result.cc_pair_ids : [ccPairId]);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(tToasts("runResolveFailed", { message }));
    } finally {
      setResolving(false);
    }
  }

  return { resolving, resolve, resolveRun, resolveMatching };
}
