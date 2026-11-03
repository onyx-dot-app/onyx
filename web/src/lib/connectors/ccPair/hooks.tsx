"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate, type SWRConfiguration } from "swr";
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
  HoveredLine,
  ThroughputActivityLinks,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import type {
  CCPairFullInfo,
  CCPairRun,
  CCPairRunErrors,
  CCPairRunKind,
  CCPairRunsResponse,
  CCPairRef,
  CCPairRunLevel,
  CCPairRunsQuery,
  CCPairRunStatusGroup,
  IndexingConnectorRow,
  IndexingConnectorsResponse,
  IndexingRun,
} from "@/lib/connectors/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  resolveAllErrorsForCCPair,
  resolveErrors,
  waitForTargetedReindexJobs,
} from "@/lib/targeted_reindex";
import type {
  ResolveAllSubmitted,
  TargetedReindexOutcome,
} from "@/lib/targeted_reindex";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";

// ---------------------------------------------------------------------------
// useStatusChange
// ---------------------------------------------------------------------------

/** Pauses, resumes, or re-enables a cc-pair, confirming first when it is invalid. */
export function useStatusChange(
  ccPair: Pick<CCPairFullInfo, "id" | "name" | "status"> | null
) {
  const t = useTranslations("admin.connector");
  const [isUpdating, setIsUpdating] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);

  const updateStatus = async (newStatus: ConnectorCredentialPairStatus) => {
    if (!ccPair) return false;

    setIsUpdating(true);

    try {
      // Call the backend to update the status
      await setCCPairStatus(ccPair.id, newStatus);

      // The status page lists the pair's state too.
      await Promise.all([
        mutate(buildCCPairInfoUrl(ccPair.id)),
        mutate(
          (cached) =>
            typeof cached === "string" &&
            cached.startsWith(SWR_KEYS.indexMonitoringConnectorsPrefix)
        ),
      ]);
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

/** Which section of an activity panel a run sits in. A queued run has nothing to report yet, so it sits in none. */
export type ActivitySection =
  | "failures"
  | "errors"
  | "running"
  | "success"
  | "canceled";

/** How one section narrows the runs feed. */
export interface ActivityRunsFilter {
  statusGroups: CCPairRunStatusGroup[];
  errors: CCPairRunErrors | null;
  superseded: boolean | null;
  resolved: boolean | null;
}

const NOT_FAILED: CCPairRunStatusGroup[] = ["running", "succeeded", "canceled"];

/** A section of runs with no errors recorded, which hold nothing to resolve. */
function cleanRuns(group: CCPairRunStatusGroup): SectionFilter {
  return {
    open: {
      statusGroups: [group],
      errors: "none",
      superseded: null,
      resolved: null,
    },
    closed: null,
  };
}

interface SectionFilter {
  open: ActivityRunsFilter;
  /** The resolved or superseded runs, null for a section that holds nothing to resolve. */
  closed: ActivityRunsFilter | null;
}

/** Each section's open runs and its closed (resolved or superseded) ones. */
export const ACTIVITY_SECTION_FILTER = {
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
      superseded: false,
      resolved: false,
    },
    closed: {
      statusGroups: NOT_FAILED,
      errors: "resolved",
      superseded: true,
      resolved: true,
    },
  },
  running: cleanRuns("running"),
  success: cleanRuns("succeeded"),
  canceled: cleanRuns("canceled"),
} satisfies Record<ActivitySection, SectionFilter>;

/** The sections the activity panel's default level (Errors) lists. */
export const DEFAULT_ACTIVITY_SECTIONS = [
  "failures",
  "errors",
] as const satisfies readonly ActivitySection[];

/** Whether the section's runs carry failures or errors a viewer can inspect and resolve. */
export function sectionResolves(section: ActivitySection): boolean {
  return ACTIVITY_SECTION_FILTER[section].closed !== null;
}

/** A run's identity across kinds, since attempt ids repeat between kinds. */
export function runKey(run: CCPairRun): string {
  return `${run.kind}-${run.attempt.id}`;
}

const ACTIVITY_PAGE_SIZE = 20;

/** Which pairs an activity feed reads: one pair, with what the viewer may resolve on it, or every readable one. */
export type ActivityScope =
  | { ccPairId: number; canResolve: boolean; canResolveRuns: boolean }
  | "fleet";

/** One run in an activity panel, with the pair it ran on and what the viewer may do to it. */
export interface ActivityItem {
  ccPairId: number;
  run: CCPairRun;
  /** Set when the feed spans pairs, so the card shows the pair. */
  connector: CCPairRef | undefined;
  /** The viewer may re-fetch single documents of the run's pair. */
  canResolve: boolean;
  /** The viewer may mark the run resolved. */
  canResolveRuns: boolean;
}

export interface ActivitySectionState {
  section: ActivitySection;
  /** Lists the section's resolved and superseded runs rather than its open ones. */
  closed: boolean;
  runs: ActivityItem[];
  /** Runs in the section, loaded or not. */
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

interface ActivityFeed {
  ccPairId: number | null;
  revalidate: () => Promise<void>;
}

// SWR's key-filter mutate skips useSWRInfinite keys, so each mounted feed registers its own revalidate.
const activityFeeds = new Set<ActivityFeed>();

/** The creation times an activity feed keeps, as ISO times. `until` is exclusive. */
export interface ActivityTimeRange {
  since: string | null;
  until: string | null;
}

/** What narrows every section of a panel alike. */
export interface ActivityNarrowing {
  /** Matched against error messages. */
  q: string;
  range: ActivityTimeRange;
  /** The fleet's pairs. Empty leaves the backend's scope: readable on the feed, operated on the batch routes. A pair's feed ignores it. */
  ccPairIds: readonly number[];
}

export const ALL_ACTIVITY: ActivityNarrowing = {
  q: "",
  range: { since: null, until: null },
  ccPairIds: [],
};

function scopePairId(scope: ActivityScope): number | null {
  return scope === "fleet" ? null : scope.ccPairId;
}

/** The feed URL of one page of a section's runs. */
function activityFeedKey(
  ccPairId: number | null,
  filter: ActivityRunsFilter,
  closed: boolean,
  narrowing: ActivityNarrowing,
  pageNum: number,
  pageSize: number
): string {
  const query: CCPairRunsQuery = {
    pageNum,
    pageSize,
    since: narrowing.range.since,
    until: narrowing.range.until,
    kinds: null,
    q: narrowing.q,
    ...filter,
    // A search finds superseded runs too, under their open section. The closed feed keeps its superseded ones.
    superseded: narrowing.q && !closed ? null : filter.superseded,
  };
  return ccPairId === null
    ? SWR_KEYS.indexMonitoringRuns(query, narrowing.ccPairIds)
    : SWR_KEYS.ccPairRuns(ccPairId, query);
}

export interface ActivityItemsOptions {
  /** Fetches nothing while false. */
  enabled: boolean;
  pollMs: number;
  /** Narrows the section's status groups further. Default: the section's own. */
  statusGroups?: CCPairRunStatusGroup[] | null;
}

/** One section of the scope, its open runs or its `closed` ones. `more` loads the next page and a new narrowing starts over. */
export function useActivityItems(
  scope: ActivityScope,
  section: ActivitySection,
  closed: boolean,
  narrowing: ActivityNarrowing,
  { enabled, pollMs, statusGroups = null }: ActivityItemsOptions
): ActivitySectionState {
  const ccPairId = scopePairId(scope);
  const pair = scope === "fleet" ? null : scope;
  // Primitives, so a scope rebuilt every render does not remap the runs.
  const canResolve = pair?.canResolve ?? null;
  const canResolveRuns = pair?.canResolveRuns ?? null;
  const sectionFilter =
    ACTIVITY_SECTION_FILTER[section][closed ? "closed" : "open"];
  const { q, range } = narrowing;
  const ccPairIds = narrowing.ccPairIds.join(",");
  const { data, error, isLoading, size, setSize, mutate } =
    useSWRInfinite<FeedPage>(
      (pageIndex, previous: FeedPage | null) => {
        if (!enabled || sectionFilter === null) return null;
        if (previous !== null && previous.items.length < ACTIVITY_PAGE_SIZE) {
          return null;
        }
        const filter =
          statusGroups === null
            ? sectionFilter
            : { ...sectionFilter, statusGroups };
        return activityFeedKey(
          ccPairId,
          filter,
          closed,
          narrowing,
          pageIndex,
          ACTIVITY_PAGE_SIZE
        );
      },
      errorHandlingFetcher,
      { refreshInterval: pollMs, keepPreviousData: true }
    );
  useEffect(() => {
    void setSize(1);
  }, [q, range.since, range.until, ccPairIds, setSize]);
  useEffect(() => {
    const feed: ActivityFeed = {
      ccPairId,
      revalidate: async () => {
        await mutate();
      },
    };
    activityFeeds.add(feed);
    return () => {
      activityFeeds.delete(feed);
    };
  }, [ccPairId, mutate]);
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
          const key = runKey(item.run);
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        })
    );
  }, [data, ccPairId, canResolve, canResolveRuns]);
  const first = data?.[0];
  const last = data?.[data.length - 1];
  return {
    section,
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

/** How many open runs the sections list together under the narrowing, read from one single-run page each, or null until known. Disabled, it fetches nothing. A failed read stays null and SWR retries it. */
export function useActivityRunsCount(
  scope: ActivityScope,
  sections: readonly ActivitySection[],
  narrowing: ActivityNarrowing,
  enabled: boolean,
  config: Pick<SWRConfiguration, "refreshInterval" | "keepPreviousData"> = {},
  /** Narrows the errors section's status groups, as a level's feed does. */
  errorStatusGroups: CCPairRunStatusGroup[] | null = null
): number | null {
  const ccPairId = scopePairId(scope);
  const keys = enabled
    ? sections.map((section) =>
        activityFeedKey(
          ccPairId,
          section === "errors" && errorStatusGroups !== null
            ? {
                ...ACTIVITY_SECTION_FILTER.errors.open,
                statusGroups: errorStatusGroups,
              }
            : ACTIVITY_SECTION_FILTER[section].open,
          false,
          narrowing,
          0,
          1
        )
      )
    : null;
  const { data } = useSWR<number>(
    keys === null ? null : SWR_KEYS.activityRunsCount(keys),
    async ([, ...urls]: readonly string[]) => {
      const pages = await Promise.all(
        urls.map((url) => errorHandlingFetcher<FeedPage>(url))
      );
      return pages.reduce((sum, page) => sum + page.total_items, 0);
    },
    config
  );
  return data ?? null;
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
  return Promise.all([
    mutate(
      (key) =>
        (typeof key === "string" &&
          prefixes.some((prefix) => key.startsWith(prefix))) ||
        (Array.isArray(key) && key[0] === SWR_KEYS.activityRunsCountTag)
    ),
    ...Array.from(activityFeeds)
      .filter(
        (feed) => feed.ccPairId === null || ccPairIds.includes(feed.ccPairId)
      )
      .map((feed) => feed.revalidate()),
  ]);
}

// The connectors route's largest page.
const CONNECTOR_CHOICES_PAGE_SIZE = 100;

export interface ConnectorChoices {
  connectors: IndexingConnectorRow[];
  /** The first page for the search is on its way, or a later one is. */
  isLoading: boolean;
  failed: boolean;
  hasMore: boolean;
  /** Asks for the next page. */
  more: () => void;
  retry: () => void;
}

/** The readable pairs whose names match `q`, a page at a time, for a connector picker. */
export function useConnectorChoices(q: string): ConnectorChoices {
  const { data, error, isLoading, size, setSize, mutate } =
    useSWRInfinite<IndexingConnectorsResponse>(
      (pageNum, previous: IndexingConnectorsResponse | null) => {
        if (
          previous !== null &&
          previous.items.length < CONNECTOR_CHOICES_PAGE_SIZE
        )
          return null;
        return SWR_KEYS.indexMonitoringConnectors({
          pageNum,
          pageSize: CONNECTOR_CHOICES_PAGE_SIZE,
          q,
          status: null,
        });
      },
      errorHandlingFetcher,
      { keepPreviousData: true }
    );
  useEffect(() => {
    void setSize(1);
  }, [q, setSize]);
  // The list sorts by status, so a pair whose status moves between two page reads can land on both.
  const connectors = useMemo(() => {
    const seen = new Set<number>();
    return (data ?? []).flatMap((page) =>
      page.items.filter((row) => {
        if (seen.has(row.cc_pair_id)) return false;
        seen.add(row.cc_pair_id);
        return true;
      })
    );
  }, [data]);
  const first = data?.[0];
  const last = data?.[data.length - 1];
  return {
    connectors,
    isLoading: isLoading || (data !== undefined && size > data.length),
    failed: error !== undefined,
    hasMore:
      first !== undefined &&
      last !== undefined &&
      connectors.length < first.total_items &&
      last.items.length === CONNECTOR_CHOICES_PAGE_SIZE,
    more: () => void setSize(size + 1),
    retry: () => void mutate(),
  };
}

/** How many open runs of the level, or of every level when `level` is null, the batch resolve would mark under the narrowing, on the pair or the pairs the caller operates. Disabled, it fetches nothing. */
export function useResolvableRunsCount(
  scope: ActivityScope,
  enabled: boolean,
  level: CCPairRunLevel | null,
  narrowing: ActivityNarrowing,
  pollMs: number
): { count: number; isLoading: boolean } {
  const ccPairId = scopePairId(scope);
  const { q, range } = narrowing;
  const { data, isLoading } = useSWR<{ count: number }>(
    !enabled
      ? null
      : ccPairId === null
        ? SWR_KEYS.indexMonitoringResolvableRunsCount(
            level,
            q,
            range.since,
            range.until,
            narrowing.ccPairIds
          )
        : SWR_KEYS.ccPairResolvableRunsCount(
            ccPairId,
            level,
            q,
            range.since,
            range.until
          ),
    errorHandlingFetcher,
    { refreshInterval: pollMs, keepPreviousData: true }
  );
  return { count: data?.count ?? 0, isLoading };
}

// ---------------------------------------------------------------------------
// useResolveRunErrors
// ---------------------------------------------------------------------------

// Error ids with a retry in flight per run, or "all" for a run-wide retry.
// Module-level, so a remounted panel still sees them.
const retryingByRun = new Map<number, Set<number> | "all">();

function isRetrying(runId: number, errorIds: number[] | null): boolean {
  const held = retryingByRun.get(runId);
  if (held === undefined) return false;
  if (held === "all" || errorIds === null) return true;
  return errorIds.some((id) => held.has(id));
}

function holdRetry(runId: number, errorIds: number[] | null): void {
  const held = retryingByRun.get(runId);
  if (errorIds === null) retryingByRun.set(runId, "all");
  else if (held instanceof Set) errorIds.forEach((id) => held.add(id));
  else retryingByRun.set(runId, new Set(errorIds));
}

function releaseRetry(runId: number, errorIds: number[] | null): void {
  const held = retryingByRun.get(runId);
  if (errorIds === null || !(held instanceof Set)) {
    retryingByRun.delete(runId);
    return;
  }
  errorIds.forEach((id) => held.delete(id));
  if (held.size === 0) retryingByRun.delete(runId);
}

/** Resolves a run's document errors by a targeted reindex, or marks the run resolved, and refreshes every feed it appears in, one submit at a time. */
export function useResolveRunErrors() {
  const tToasts = useTranslations("admin.connector.toasts");
  const [resolving, setResolving] = useState(false);

  // Holds the buttons only for the submit. A progress toast follows the jobs
  // and is replaced by their outcome, so other runs can be retried meanwhile.
  async function resolve(item: ActivityItem, errorIds: number[] | null) {
    const runId = item.run.attempt.id;
    // Retrying errors already in flight would only resolve nothing.
    if (resolving || isRetrying(runId, errorIds)) return;
    setResolving(true);
    let submitted: ResolveAllSubmitted;
    try {
      submitted =
        errorIds === null
          ? await resolveAllErrorsForCCPair(item.ccPairId, item.run.attempt.id)
          : await resolveErrors(errorIds);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(tToasts("targetedReindexFailed", { message }));
      return;
    } finally {
      setResolving(false);
    }
    void refreshFeeds([item.ccPairId]);
    if (submitted.total_error_ids === 0) {
      toast.success(tToasts("noUnresolvedErrors"));
      return;
    }

    const toastId = `targeted-reindex-${submitted.job_ids[0]}`;
    toast.info(
      tToasts("targetedReindexRunning", { count: submitted.total_error_ids }),
      { id: toastId, duration: Infinity }
    );
    holdRetry(runId, errorIds);
    let outcome: TargetedReindexOutcome;
    try {
      outcome = await waitForTargetedReindexJobs(submitted.job_ids);
    } finally {
      releaseRetry(runId, errorIds);
    }
    if (!outcome.finished) {
      toast.error(tToasts("targetedReindexIncomplete"), { id: toastId });
    } else if (outcome.still_failing > 0) {
      toast.warning(
        tToasts("targetedReindexPartial", {
          resolved: outcome.resolved,
          failing: outcome.still_failing,
        }),
        { id: toastId }
      );
    } else {
      toast.success(
        tToasts("targetedReindexDone", { resolved: outcome.resolved }),
        { id: toastId }
      );
    }
    await refreshFeeds([item.ccPairId]);
  }

  // Marks the run resolved without a targeted reindex: it keeps its status.
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

  // Marks every open run of the level, or of every level, the panel lists under the narrowing resolved.
  async function resolveMatching(
    scope: ActivityScope,
    level: CCPairRunLevel | null,
    narrowing: ActivityNarrowing
  ) {
    if (resolving) return;
    setResolving(true);
    const ccPairId = scopePairId(scope);
    const { q, range } = narrowing;
    try {
      const result = await resolveMatchingRuns(ccPairId, {
        level,
        q: q || null,
        since: range.since,
        until: range.until,
        kinds: null,
        cc_pair_ids:
          ccPairId === null && narrowing.ccPairIds.length > 0
            ? [...narrowing.ccPairIds]
            : null,
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

// ---------------------------------------------------------------------------
// useLatestCCPairRun
// ---------------------------------------------------------------------------

/** The pair's newest run of one kind. The response's `kinds` lists every kind the pair runs. */
export function useLatestCCPairRun(
  ccPairId: number,
  kind: CCPairRunKind,
  enabled: boolean,
  pollMs: number
) {
  return useSWR<CCPairRunsResponse>(
    enabled
      ? SWR_KEYS.ccPairRuns(ccPairId, {
          pageNum: 0,
          pageSize: 1,
          since: null,
          until: null,
          kinds: [kind],
          statusGroups: null,
          q: "",
          errors: null,
          superseded: null,
          resolved: null,
        })
      : null,
    errorHandlingFetcher,
    { refreshInterval: pollMs }
  );
}

function panelOpenKey(scope: ActivityScope): string {
  return `onyx.activityPanel.open.${scope === "fleet" ? "fleet" : scope.ccPairId}`;
}

function readPanelChoice(key: string): boolean | null {
  try {
    const stored = window.sessionStorage.getItem(key);
    return stored === null ? null : stored === "true";
  } catch {
    return null;
  }
}

export interface ActivityPanelOpen {
  open: boolean;
  /** Holds for the rest of the session. */
  setOpen: (open: boolean) => void;
}

/** Whether the scope's activity panel shows: the admin's choice this session, else open once the default level holds an open item, running runs with errors included. */
export function useActivityPanelOpen(scope: ActivityScope): ActivityPanelOpen {
  const key = panelOpenKey(scope);
  // Read after mount: the server renders without storage, so a first render that read it would not hydrate.
  const [choice, setChoice] = useState<boolean | null>(null);
  useEffect(() => {
    setChoice(readPanelChoice(key));
  }, [key]);
  // Settled once from the first count, so a revalidation never opens or closes the panel under the admin.
  const [byDefault, setByDefault] = useState<boolean | null>(null);
  const count = useActivityRunsCount(
    scope,
    DEFAULT_ACTIVITY_SECTIONS,
    ALL_ACTIVITY,
    byDefault === null && choice === null
  );
  useEffect(() => {
    if (count !== null && byDefault === null) setByDefault(count > 0);
  }, [count, byDefault]);
  function setOpen(open: boolean) {
    setChoice(open);
    try {
      window.sessionStorage.setItem(key, String(open));
    } catch {
      // Without storage the choice holds until the page unloads.
    }
  }
  return { open: choice ?? byDefault ?? false, setOpen };
}

/** What the chart and an activity panel on one page tell each other. */
export interface ActivityPanelLinks {
  onHoverAttempt: (attemptId: number | null) => void;
  focusAttemptId: number | null;
  outlinedAttemptIds: number[];
}

export interface ActivityChartLinks {
  chart: ThroughputActivityLinks;
  panel: ActivityPanelLinks;
}

export interface ActivityChartLinksOptions {
  /** Runs as a failure line focuses its card, such as to open the panel that lists it. */
  onFocusAttempt?: (attemptId: number) => void;
}

/** One page's chart and activity panel, linked: a hovered card marks its run on the chart, a failure line click focuses its card, a hovered line outlines its runs' cards. */
export function useActivityChartLinks({
  onFocusAttempt,
}: ActivityChartLinksOptions = {}): ActivityChartLinks {
  const [hoveredAttemptId, setHoveredAttemptId] = useState<number | null>(null);
  const [focusAttemptId, setFocusAttemptId] = useState<number | null>(null);
  const [outlinedAttemptIds, setOutlinedAttemptIds] = useState<number[]>([]);
  return {
    chart: {
      hoveredAttemptId,
      onFocusAttempt: (attemptId: number) => {
        onFocusAttempt?.(attemptId);
        setFocusAttemptId(attemptId);
      },
      onHoverLine: (line: HoveredLine | null) =>
        setOutlinedAttemptIds(line?.attemptIds ?? []),
    },
    panel: {
      onHoverAttempt: (attemptId: number | null) => {
        setHoveredAttemptId(attemptId);
        // The focus lift ends once the pointer leaves a card, so it does not hold for the page's life.
        if (attemptId === null) setFocusAttemptId(null);
      },
      focusAttemptId,
      outlinedAttemptIds,
    },
  };
}
