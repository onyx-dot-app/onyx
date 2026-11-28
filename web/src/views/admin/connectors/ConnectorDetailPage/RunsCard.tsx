"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { richNodes } from "@opal/utils";
import { useFormatter, useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import {
  Button,
  Card,
  Divider,
  Dropdown,
  SelectButton,
  MessageCard,
  Pagination,
  Badge,
  Tooltip,
  Text,
  useCreateModal,
} from "@opal/components";
import { IllustrationContent, Section, toast } from "@opal/layouts";
import { SvgLongWait, SvgNoResult } from "@opal/illustrations";
import { CardLoader, IconLoader } from "@opal/loaders";
import {
  SvgActivity,
  SvgCheckCircle,
  SvgSlowMotion,
  SvgXCircle,
  SvgXOctagon,
} from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { cancelIndexAttempt } from "@/lib/connectors/svc";
import type {
  CCPairRun,
  CCPairRunKind,
  CCPairRunsResponse,
  CCPairRunStatusGroup,
} from "@/lib/connectors/types";
import ExceptionTraceModal from "@/sections/modals/PreviewModal/ExceptionTraceModal";
import {
  DEFAULT_PAIR_WINDOW,
  PAIR_WINDOWS,
  ThroughputWindowPicker,
  pickedWindowStart,
  rangeWithin,
  type PickedWindow as SharedWindow,
  type PickerWindow,
  type SliceRange,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import RunRow, {
  RUN_KIND_ICONS,
  hasInlineDetails,
  runErrorText,
} from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import { useFocusedRow } from "@/views/admin/connectors/ConnectorDetailPage/focusMode";
import type { RunRef } from "@/views/admin/connectors/ConnectorDetailPage/runLink";

const PAGE_SIZE = 10;
// A row's run list is a glance, and the connector page holds the rest.
const EMBEDDED_PAGE_SIZE = 6;
export const RUNS_POLL_MS = 5000;

const LOADER_ROWS = 3;

const STATUS_GROUPS: CCPairRunStatusGroup[] = [
  "running",
  "succeeded",
  "failed",
  "canceled",
];

// The header counts. A group with no runs shows no tag.
const COUNT_TAGS = [
  { group: "succeeded", icon: SvgCheckCircle, color: "success" },
  { group: "running", icon: IconLoader, color: "info" },
  { group: "failed", icon: SvgXOctagon, color: "error" },
  { group: "canceled", icon: SvgXCircle, color: "default" },
] as const;

const ALL = "all";

export interface RunsCardProps {
  ccPairId: number;
  /** Shows the cancel action on running or queued index attempts. */
  canOperate: boolean;
  /** Renders a compact list for a card that already frames it: the filters, the newest runs with running ones first, no counts or pages. */
  embedded?: boolean;
  /** Buttons beside the filters in the embedded list. */
  actions?: ReactNode;
  /** Rendered under the runs of the embedded list. */
  footer?: ReactNode;
  /** The page's window, shared with the status card. Without it the list keeps its own over the same windows. */
  sharedWindow?: SharedWindow;
  onSharedWindowChange?: (window: PickerWindow) => void;
  /** A chart span that narrows the list inside the shared window. The shared picker shows it, and its X calls `onClearRange`. */
  range?: SliceRange | null;
  onClearRange?: () => void;
  /** Called when a run line's stage details or check results open or close, so the page can step back around it. */
  onFocusChange?: (focused: boolean) => void;
  /** The index attempt of the activity the page's panel points at: its run line lifts. */
  liftedAttemptId?: number | null;
  /** A run to open, such as one a link points at. A list that misses it widens to that kind over all time. Each new object opens it again. */
  openRun?: RunRef | null;
}

/** The empty list at the design's 64 px illustration. */
function NoRecentRuns() {
  const t = useTranslations("admin.connector.runs.empty");
  return (
    // IllustrationContent pads 20 px, and 20 px of margin makes the design's 40 px above and below.
    <Section height="fit" className="my-5">
      <IllustrationContent
        size="sm"
        illustration={SvgLongWait}
        title={t("title")}
      />
    </Section>
  );
}

/** A run's key in the list. */
function runKey(run: CCPairRun): string {
  return `${run.kind}-${run.attempt.id}`;
}

/** The pair's index attempts and, when perm-synced, its permission syncs, newest first. */
export default function RunsCard({
  ccPairId,
  canOperate,
  embedded = false,
  actions,
  footer,
  sharedWindow,
  onSharedWindowChange,
  onFocusChange,
  range = null,
  onClearRange,
  liftedAttemptId = null,
  openRun = null,
}: RunsCardProps) {
  const t = useTranslations("admin.connector.runs");
  const format = useFormatter();
  const [page, setPage] = useState(1);
  const [ownWindow, setOwnWindow] = useState<PickerWindow>(DEFAULT_PAIR_WINDOW);
  const timeWindow = sharedWindow?.window ?? ownWindow;
  // The past runs row on the empty state widens the list to all time until the window or slice changes.
  const [widened, setWidened] = useState(false);
  const widen = useCallback(() => {
    setPage(1);
    setWidened(true);
  }, []);
  const windowRange = rangeWithin(
    pickedWindowStart({ window: timeWindow }),
    range
  );
  // A new window or slice starts the list over at its first page. The key is
  // the selection, not the moving start, so a passing minute keeps the page.
  const selection = [timeWindow, range?.since ?? "", range?.until ?? ""].join(
    "|"
  );
  const [pagedSelection, setPagedSelection] = useState(selection);
  if (pagedSelection !== selection) {
    setPagedSelection(selection);
    setPage(1);
    setWidened(false);
  }
  const since = widened ? null : windowRange.since;
  const until = widened ? null : windowRange.until;
  const focus = useFocusedRow<string>(onFocusChange);
  const [kind, setKind] = useState<CCPairRunKind | null>(null);
  const [statusGroup, setStatusGroup] = useState<CCPairRunStatusGroup | null>(
    null
  );
  const [logRun, setLogRun] = useState<CCPairRun | null>(null);
  const logRunModal = useCreateModal();

  const pageSize = embedded ? EMBEDDED_PAGE_SIZE : PAGE_SIZE;
  const kinds = kind === null ? null : [kind];
  const key = SWR_KEYS.ccPairRuns(ccPairId, {
    pageNum: page - 1,
    pageSize,
    since,
    until,
    kinds,
    statusGroups: statusGroup === null ? null : [statusGroup],
    q: "",
    errors: null,
    superseded: null,
    resolved: null,
  });
  const {
    data,
    error,
    isLoading,
    mutate: reloadRuns,
  } = useSWR<CCPairRunsResponse>(key, errorHandlingFetcher, {
    refreshInterval: RUNS_POLL_MS,
    keepPreviousData: true,
  });
  // An empty window with no other filter counts the pair's runs before it, for the link to them.
  const emptyWindow =
    data !== undefined &&
    data.items.length === 0 &&
    since !== null &&
    kind === null &&
    statusGroup === null;
  const { data: allTime } = useSWR<CCPairRunsResponse>(
    emptyWindow
      ? SWR_KEYS.ccPairRuns(ccPairId, {
          pageNum: 0,
          pageSize: 1,
          since: null,
          kinds: null,
          statusGroups: null,
          q: "",
          errors: null,
          until: null,
          superseded: null,
          resolved: null,
        })
      : null,
    errorHandlingFetcher,
    { refreshInterval: RUNS_POLL_MS }
  );
  const pastRuns = allTime?.total_items ?? 0;
  // The newest page can miss a long run that newer runs pushed off it, so the embedded list fetches the running runs on their own and shows them first. A status filter already decides whether running runs show.
  const runningFirst = embedded && statusGroup === null;
  const { data: runningData } = useSWR<CCPairRunsResponse>(
    runningFirst
      ? SWR_KEYS.ccPairRuns(ccPairId, {
          pageNum: 0,
          pageSize,
          since,
          until,
          kinds,
          statusGroups: ["running"],
          q: "",
          errors: null,
          superseded: null,
          resolved: null,
        })
      : null,
    errorHandlingFetcher,
    { refreshInterval: RUNS_POLL_MS, keepPreviousData: true }
  );
  const items = useMemo(() => {
    // keepPreviousData holds the last running runs after the fetch stops, so they are dropped here.
    const runningRuns = runningFirst ? (runningData?.items ?? []) : [];
    const runningKeys = new Set(runningRuns.map(runKey));
    // Running runs come on top of the newest page, so the merge is cut back to the page.
    return [
      ...runningRuns,
      ...(data?.items ?? []).filter((run) => !runningKeys.has(runKey(run))),
    ].slice(0, pageSize);
  }, [runningFirst, runningData, data, pageSize]);
  const { retain, setOpen } = focus;
  useEffect(() => {
    if (data !== undefined) retain(items.map(runKey));
  }, [data, items, retain]);
  // A focused row with no details has no control to close it, so a link to one only selects the tab.
  const openedRun = useRef<RunRef | null>(null);
  const revealedRun = useRef<RunRef | null>(null);
  useEffect(() => {
    if (openRun === null || openedRun.current === openRun) return;
    if (data === undefined || isLoading) return;
    const run = items.find(
      (item) => item.kind === openRun.kind && item.attempt.id === openRun.id
    );
    if (run !== undefined) {
      openedRun.current = openRun;
      if (hasInlineDetails(run)) setOpen(runKey(run), true);
      return;
    }
    // A link can point at any past run, so the list widens to its kind over all time and pages back until it lists.
    if (revealedRun.current !== openRun) {
      revealedRun.current = openRun;
      setKind(openRun.kind);
      setStatusGroup(null);
      widen();
      return;
    }
    if (page * pageSize < data.total_items) setPage(page + 1);
    else openedRun.current = openRun;
  }, [openRun, data, isLoading, items, page, pageSize, setOpen, widen]);

  function pickWindow(next: PickerWindow) {
    // Picking the same window again still leaves the widened view.
    setWidened(false);
    if (sharedWindow === undefined) setOwnWindow(next);
    else onSharedWindowChange?.(next);
  }

  function pickKind(next: CCPairRunKind | null) {
    setKind(next);
    setPage(1);
  }

  function pickStatusGroup(next: CCPairRunStatusGroup | null) {
    setStatusGroup(next);
    setPage(1);
  }

  async function cancel(run: CCPairRun) {
    const failure = await cancelIndexAttempt(
      run.attempt.id,
      t("toasts.cancelFailed")
    );
    if (failure !== null) {
      toast.error(failure);
      return;
    }
    toast.success(t("toasts.canceled"));
    // The status page lists this pair's summary too, so its list refreshes with the runs.
    await Promise.all([
      mutate(key),
      mutate(buildCCPairInfoUrl(ccPairId)),
      mutate(
        (cached) =>
          typeof cached === "string" &&
          cached.startsWith(SWR_KEYS.indexMonitoringConnectorsPrefix)
      ),
    ]);
  }

  const kindOptions = data?.kinds ?? ["indexing"];
  const totalItems = data?.total_items ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  // Polling can shrink the feed under an open page.
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);
  // A window is always set, so only a narrowing inside it counts as a filter.
  const filtered = kind !== null || statusGroup !== null || range !== null;

  const runList =
    error !== undefined ? (
      <MessageCard
        variant="error"
        title={t("loadError.title")}
        rightChildren={
          embedded && (
            <Button prominence="secondary" onClick={() => void reloadRuns()}>
              {t("loadError.retry")}
            </Button>
          )
        }
      />
    ) : isLoading && data === undefined ? (
      <Section alignItems="stretch" gap={1} height="fit">
        {Array.from({ length: LOADER_ROWS }, (_, index) => (
          <CardLoader
            key={index}
            color="background-tint-00"
            border="none"
            rounding={2}
            padding={2}
          />
        ))}
      </Section>
    ) : emptyWindow ? (
      <Section alignItems="stretch" gap={0} height="fit">
        <NoRecentRuns />
        {pastRuns > 0 && (
          // Opens nothing in place: it widens the list to all time, which replaces the empty state.
          <Divider
            title={t("empty.pastRuns", { count: pastRuns })}
            foldable
            chevronPosition="start"
            foldedChevron="down"
            open={false}
            onOpenChange={widen}
          />
        )}
      </Section>
    ) : items.length === 0 ? (
      filtered ? (
        <IllustrationContent
          illustration={SvgNoResult}
          title={t("empty.filteredTitle")}
        />
      ) : (
        <NoRecentRuns />
      )
    ) : (
      <Section alignItems="stretch" gap={1} height="fit">
        {items.map((run) => (
          <RunRow
            key={runKey(run)}
            run={run}
            canCancel={canOperate}
            onCancel={() => void cancel(run)}
            onViewLogs={() => {
              setLogRun(run);
              logRunModal.toggle(true);
            }}
            open={focus.isOpen(runKey(run))}
            onOpenChange={(open) => focus.setOpen(runKey(run), open)}
            dimmed={focus.isDimmed(runKey(run))}
            lifted={
              run.kind === "indexing" && run.attempt.id === liftedAttemptId
            }
          />
        ))}
      </Section>
    );
  const logModal = (
    <logRunModal.Provider>
      {logRun !== null && (
        <ExceptionTraceModal
          onOutsideClick={() => logRunModal.toggle(false)}
          exceptionTrace={runErrorText(logRun) ?? ""}
          title={t(`errorModal.${logRun.kind}`)}
        />
      )}
    </logRunModal.Provider>
  );

  // On the row's white header an idle filter is plain text, as the window picker is; the full card's tint already hides the filter fill.
  const filterVariant = embedded ? "select-heavy" : "select-filter";
  const filters = (
    <Section
      flexDirection="row"
      justifyContent="start"
      gap={1}
      height="fit"
      className="min-w-0 flex-1"
      wrap
    >
      {/* The window is always set, so it is the connector page's picker, not a clearable filter. */}
      <ThroughputWindowPicker
        windows={PAIR_WINDOWS}
        value={timeWindow}
        // A widened list reaches past the chart's window, and says so.
        label={widened ? t("window.all") : undefined}
        onChange={pickWindow}
        selection={range}
        onClearSelection={onClearRange}
      />
      {kindOptions.length > 1 && (
        <Dropdown>
          <Dropdown.Trigger asChild>
            <SelectButton
              variant={filterVariant}
              chevron
              labelFont="main-ui-action"
              icon={SvgSlowMotion}
              state={kind !== null ? "selected" : "empty"}
              onClear={() => pickKind(null)}
            >
              {kind === null ? t("kinds.all") : t(`kinds.${kind}`)}
            </SelectButton>
          </Dropdown.Trigger>
          <Dropdown.Data
            label={t("kinds.label")}
            value={kind ?? ALL}
            onSelect={(option) =>
              pickKind(
                kindOptions.find((candidate) => candidate === option.value) ??
                  null
              )
            }
            items={[
              {
                kind: "option" as const,
                value: ALL,
                title: t("kinds.all"),
              },
              ...kindOptions.map((candidate) => ({
                kind: "option" as const,
                value: candidate,
                icon: RUN_KIND_ICONS[candidate],
                title: t(`kinds.${candidate}`),
              })),
            ]}
          />
        </Dropdown>
      )}
      <Dropdown>
        <Dropdown.Trigger asChild>
          <SelectButton
            variant={filterVariant}
            chevron
            labelFont="main-ui-action"
            icon={SvgActivity}
            state={statusGroup !== null ? "selected" : "empty"}
            onClear={() => pickStatusGroup(null)}
          >
            {statusGroup === null
              ? t("statusGroups.all")
              : t(`statusGroups.${statusGroup}`)}
          </SelectButton>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("statusGroups.label")}
          value={statusGroup ?? ALL}
          onSelect={(option) =>
            pickStatusGroup(
              STATUS_GROUPS.find((group) => group === option.value) ?? null
            )
          }
          items={[
            {
              kind: "option" as const,
              value: ALL,
              title: t("statusGroups.all"),
            },
            ...STATUS_GROUPS.map((group) => ({
              kind: "option" as const,
              value: group,
              title: t(`statusGroups.${group}`),
            })),
          ]}
        />
      </Dropdown>
    </Section>
  );

  const body = (
    <>
      {logModal}
      <Section alignItems="stretch" gap={0} height="fit">
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          gap={2}
          padding={2}
          height="fit"
        >
          {filters}
          <Section
            flexDirection="row"
            justifyContent="end"
            gap={1}
            width="fit"
            height="fit"
          >
            {COUNT_TAGS.filter(
              ({ group }) => (data?.status_counts[group] ?? 0) > 0
            ).map(({ group, icon, color }) => (
              <Tooltip
                key={group}
                tooltip={t(`counts.${group}`, {
                  count: data?.status_counts[group] ?? 0,
                })}
                side="top"
              >
                <Badge
                  icon={icon}
                  title={format.number(data?.status_counts[group] ?? 0)}
                  color={color}
                />
              </Tooltip>
            ))}
          </Section>
        </Section>

        <Section alignItems="stretch" padding={1} height="fit">
          {runList}
        </Section>

        {/* 12 px in from the card's sides, in line with the run lines. */}
        {totalItems > 0 && (
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="center"
            gap={2}
            padding={2}
            width="auto"
            height="fit"
            className="mx-1"
          >
            <Text font="secondary-body" color="text-03">
              {richNodes(
                t.rich("showing", {
                  from: format.number((page - 1) * pageSize + 1),
                  to: format.number(Math.min(page * pageSize, totalItems)),
                  total: format.number(totalItems),
                  mono: (chunks) => (
                    <Text font="secondary-mono" color="text-03">
                      {String(chunks)}
                    </Text>
                  ),
                })
              )}
            </Text>
            <Pagination
              variant="list"
              currentPage={page}
              totalPages={totalPages}
              onChange={setPage}
              size="sm"
            />
          </Section>
        )}
      </Section>
    </>
  );
  // The list sits flush against the framing card's sides and bottom, which round its corners.
  if (embedded) {
    return (
      <Section
        alignItems="stretch"
        gap={0}
        height="fit"
        data-testid="connector-runs"
      >
        {logModal}
        {/* The framing card's line sits 4 px above. */}
        <Section
          flexDirection="row"
          alignItems="center"
          gap={1}
          width="auto"
          height="fit"
          className="mx-2 mt-1 mb-2"
        >
          {filters}
          {actions}
        </Section>
        {/* 4 px around run lines, so a 640 px column leaves their LineLayout above its 620 px wrap. */}
        <Section
          alignItems="stretch"
          gap={1}
          padding={1}
          height="fit"
          className="rounded-b-16 border-t border-border-01 bg-background-tint-01"
        >
          {runList}
          {footer}
        </Section>
      </Section>
    );
  }
  return (
    <Card
      color="background-tint-01"
      border="solid"
      rounding={4}
      padding={0}
      data-testid="connector-runs"
    >
      {body}
    </Card>
  );
}
