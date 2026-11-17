"use client";

import { useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  Dropdown,
  type DropdownItem,
  SelectButton,
  InputTypeIn,
  MessageCard,
  ShadowDiv,
  Badge,
  Text,
  useCreateModal,
} from "@opal/components";
import { useDebouncedValue } from "@opal/hooks";
import {
  ConfirmationModalLayout,
  Content,
  IllustrationContent,
  Section,
} from "@opal/layouts";
import { SvgLongWait } from "@opal/illustrations";
import { CardLoader, IconLoader } from "@opal/loaders";
import {
  SvgActivity,
  SvgAlertTriangle,
  SvgCheckAll,
  SvgCheckCircle,
  SvgEye,
  SvgEyeClosed,
  SvgFilter,
  SvgFold,
  SvgLinkedDots,
  SvgLoader,
  SvgXCircle,
  SvgXOctagon,
} from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { cn } from "@opal/utils";
import useIsDisplayed from "@/hooks/useIsDisplayed";
import { mergeRefs } from "@/lib/utils";
import {
  runKey,
  useActivityItems,
  useActivityRunsCount,
  useConnectorChoices,
  useHeldOpenRun,
  useResolvableRunsCount,
  useResolveRunErrors,
  DEFAULT_ACTIVITY_SECTIONS,
  type ActivityItem,
  type ActivityItemsOptions,
  type ActivityPanelLinks,
  type ActivityNarrowing,
  type ActivityScope,
  type ActivitySection,
  type ActivitySectionState,
} from "@/lib/connectors/ccPair/hooks";
import type {
  CCPairRunLevel,
  CCPairRunStatusGroup,
} from "@/lib/connectors/types";
import type { FailedItemsRoute } from "@/lib/ccPair";
import { getSourceMetadata } from "@/lib/connectors/utils";
import ActivityCard from "@/views/admin/connectors/ConnectorDetailPage/ActivityCard";
import { isActive } from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import { RUNS_POLL_MS } from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import type { SliceRange } from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import { ERROR_COUNT_TAG } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import { BESIDE } from "@/views/admin/connectors/shared/PanelPageBody";
import {
  SEARCH_DELAY_MS,
  SEARCH_MAX_LENGTH,
} from "@/views/admin/connectors/shared/search";

const LOADER_ROWS = 2;

/** Which runs the panel lists. */
type ActivityLevel =
  | "all"
  | "failures"
  | "errors"
  | "running"
  | "success"
  | "canceled";

interface LevelConfig {
  /** A static icon: the trigger and its menu option are no loading indicator. */
  icon: IconFunctionComponent;
  /** The open sections, in display order. */
  sections: readonly ActivitySection[];
  /** The batch resolve's level: null for every resolvable section, undefined on levels that list nothing open to resolve. */
  resolveLevel: CCPairRunLevel | null | undefined;
  /** Narrows the Errors section's status groups and the batch resolve's, null for all of them. */
  errorStatusGroups: CCPairRunStatusGroup[] | null;
}

const LEVELS = {
  all: {
    icon: SvgActivity,
    sections: ["failures", "errors", "running", "success", "canceled"],
    resolveLevel: null,
    errorStatusGroups: null,
  },
  failures: {
    icon: SvgXOctagon,
    sections: ["failures"],
    resolveLevel: "failures",
    errorStatusGroups: null,
  },
  errors: {
    icon: SvgAlertTriangle,
    sections: DEFAULT_ACTIVITY_SECTIONS,
    resolveLevel: null,
    errorStatusGroups: null,
  },
  // A running run with errors sits under Errors, so this level lists those first.
  running: {
    icon: SvgLoader,
    sections: ["errors", "running"],
    resolveLevel: "errors",
    errorStatusGroups: ["running"],
  },
  success: {
    icon: SvgCheckCircle,
    sections: ["success"],
    resolveLevel: undefined,
    errorStatusGroups: null,
  },
  canceled: {
    icon: SvgXCircle,
    sections: ["canceled"],
    resolveLevel: undefined,
    errorStatusGroups: null,
  },
} satisfies Record<ActivityLevel, LevelConfig>;

const LEVEL_ORDER: ActivityLevel[] = [
  "all",
  "failures",
  "errors",
  "running",
  "success",
  "canceled",
];
const DEFAULT_LEVEL: ActivityLevel = "errors";
// The open sections a focused run can sit in: a failed run under Failures, any other run with open errors under Errors.
const FOCUS_SECTIONS: ActivitySection[] = ["failures", "errors"];

// Finished runs with nothing to resolve list after Resolved. Running runs, which can still report errors, list before it.
const SETTLED: ActivitySection[] = ["success", "canceled"];

interface ActivityCountTagsProps {
  failures: number;
  errors: number;
}
/** The failed runs and the runs with document errors, as two counts for the panel header. A zero count shows no tag. */
function ActivityCountTags({ failures, errors }: ActivityCountTagsProps) {
  const t = useTranslations("admin.connector.activity");
  const format = useFormatter();
  return (
    <>
      {failures > 0 && (
        <Badge
          icon={SvgXOctagon}
          title={format.number(failures)}
          color="error"
          titleColor="text-04"
          size={6}
          tooltip={t("counts.failures", { count: failures })}
        />
      )}
      {errors > 0 && (
        <Badge
          {...ERROR_COUNT_TAG}
          title={format.number(errors)}
          titleColor="text-04"
          size={6}
          tooltip={t("counts.errors", { count: errors })}
        />
      )}
    </>
  );
}

// The panel module keeps exporting its visibility hook for callers that import it with the panel.
export { useActivityPanelOpen } from "@/lib/connectors/ccPair/hooks";

/** One card of a block, with the section its run was listed under. */
interface BlockCard {
  item: ActivityItem;
  section: ActivitySection;
  closed: boolean;
}

/** A titled run list: one open section, or the resolved runs of several. */
interface Block {
  key: string;
  title: string;
  cards: BlockCard[];
  /** The feeds the block pages through. */
  states: ActivitySectionState[];
}

/** A section's runs in display order: newest first, running runs with errors last. */
function sectionCards(state: ActivitySectionState): BlockCard[] {
  const runs =
    state.section === "errors"
      ? [...state.runs].sort(
          (a, b) => Number(isActive(a.run)) - Number(isActive(b.run))
        )
      : state.runs;
  return runs.map((item) => ({
    item,
    section: state.section,
    closed: state.closed,
  }));
}

interface BlockListProps {
  block: Block;
  resolving: boolean;
  onResolve: (item: ActivityItem, errorIds: number[] | null) => void;
  onResolveWithoutRetry: (
    item: ActivityItem,
    errorIds: number[],
    route: FailedItemsRoute
  ) => Promise<void>;
  onResolveRun: (item: ActivityItem) => void;
  links: Partial<ActivityPanelLinks>;
  /** An open card's panel opened or closed. */
  onPanelOpenChange: (
    item: ActivityItem,
    section: ActivitySection,
    open: boolean
  ) => void;
}
function BlockList({
  block,
  resolving,
  onResolve,
  onResolveWithoutRetry,
  onResolveRun,
  links,
  onPanelOpenChange,
}: BlockListProps) {
  const t = useTranslations("admin.connector.activity");
  const {
    onHoverAttempt,
    focusAttemptId = null,
    focusRequest,
    outlinedAttemptIds,
    onHoverPair,
  } = links;
  // A hovered card marks its run on the chart (index runs only) and its connector's row.
  function hoverChange(item: ActivityItem, charted: boolean) {
    const marksRun = charted && onHoverAttempt !== undefined;
    if (!marksRun && onHoverPair === undefined) return undefined;
    return (hovered: boolean) => {
      if (marksRun) onHoverAttempt(hovered ? item.run.attempt.id : null);
      onHoverPair?.(hovered ? item.ccPairId : null);
    };
  }
  return (
    <Section
      alignItems="stretch"
      gap={1}
      height="fit"
      data-testid="activity-section"
    >
      <Section
        alignItems="stretch"
        height="fit"
        data-testid="activity-section-title"
      >
        <Divider title={block.title} />
      </Section>
      {block.cards.map(({ item, section, closed }) => {
        const { kind, attempt } = item.run;
        // The chart draws index runs only.
        const charted = kind === "indexing";
        return (
          <ActivityCard
            key={runKey(item.run)}
            ccPairId={item.ccPairId}
            run={item.run}
            section={section}
            closed={closed}
            connector={item.connector}
            canResolve={item.canResolve}
            canResolveRuns={item.canResolveRuns}
            resolving={resolving}
            onResolve={(errorIds) => onResolve(item, errorIds)}
            onResolveWithoutRetry={(errorIds, route) =>
              onResolveWithoutRetry(item, errorIds, route)
            }
            onResolveRun={() => onResolveRun(item)}
            onPanelOpenChange={
              closed
                ? undefined
                : (open) => onPanelOpenChange(item, section, open)
            }
            onHoverChange={hoverChange(item, charted)}
            focused={charted && focusAttemptId === attempt.id}
            focusRequest={focusRequest}
            outlined={
              charted && (outlinedAttemptIds ?? []).includes(attempt.id)
            }
          />
        );
      })}
      {block.states
        .filter((state) => state.hasMore)
        .map((state) => (
          <Section key={state.section} height="fit">
            <Button prominence="tertiary" size="xs" onClick={state.more}>
              {t("more")}
            </Button>
          </Section>
        ))}
    </Section>
  );
}

interface ConnectorsFilterProps {
  value: number[];
  onChange: (ccPairIds: number[]) => void;
}

/** Narrows the fleet's activity to the picked connectors, from the status page's own list. */
function ConnectorsFilter({ value, onChange }: ConnectorsFilterProps) {
  const t = useTranslations("admin.connector.activity");
  const tList = useTranslations("admin.indexing.list");
  const [queryInput, setQueryInput] = useState("");
  const query = useDebouncedValue(queryInput.trim(), SEARCH_DELAY_MS);
  const choices = useConnectorChoices(query);
  // Until the typed search's page arrives, the list says so rather than "no items".
  const pending = choices.isLoading || queryInput.trim() !== query;
  const options: DropdownItem[] = choices.connectors.map((row) => ({
    kind: "option",
    value: String(row.cc_pair_id),
    title: row.name,
    icon: getSourceMetadata(row.source).icon,
  }));
  const loadingRow: DropdownItem = {
    kind: "custom",
    id: "loading",
    disabled: true,
    pinned: true,
    render: ({ props }) => (
      <Section
        flexDirection="row"
        justifyContent="start"
        gap={0.5}
        padding={0.5}
        height="fit"
        {...props}
      >
        <IconLoader />
        <Text font="secondary-body" color="text-03">
          {t("filter.connectorsLoading")}
        </Text>
      </Section>
    ),
  };
  // A failed page reads as an error, never as a list with no matches. The row is the retry, so the keyboard reaches it too.
  const errorRow: DropdownItem = {
    kind: "custom",
    id: "error",
    pinned: true,
    keepOpen: true,
    onActivate: choices.retry,
    render: ({ highlighted, props }) => (
      <Section
        flexDirection="row"
        justifyContent="between"
        gap={0.5}
        padding={0.5}
        height="fit"
        className={cn("cursor-pointer", highlighted && "bg-background-tint-02")}
        {...props}
      >
        <Text font="secondary-body" color="status-error-05">
          {t("filter.connectorsLoadError")}
        </Text>
        <Text font="secondary-action" color="text-04">
          {t("filter.connectorsRetry")}
        </Text>
      </Section>
    ),
  };
  const statusRows = choices.failed ? [errorRow] : pending ? [loadingRow] : [];
  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        <SelectButton
          variant="select-filter"
          chevron
          labelFont="main-ui-action"
          icon={SvgLinkedDots}
          state={value.length > 0 ? "selected" : "empty"}
          onClear={() => onChange([])}
        >
          {t("filter.connectors")}
        </SelectButton>
      </Dropdown.Trigger>
      <Dropdown.Data
        label={t("filter.connectors")}
        values={new Set(value.map(String))}
        search={{
          placeholder: tList("search.placeholder"),
          onChange: setQueryInput,
        }}
        onSelect={(option) => {
          const picked = Number(option.value);
          onChange(
            value.includes(picked)
              ? value.filter((ccPairId) => ccPairId !== picked)
              : [...value, picked]
          );
        }}
        items={[...statusRows, ...options]}
        onReachEnd={() => {
          if (choices.hasMore && !pending && !choices.failed) choices.more();
        }}
      />
    </Dropdown>
  );
}

export interface ActivityPanelProps extends Partial<ActivityPanelLinks> {
  /** One pair's runs, or every readable pair's. */
  scope: ActivityScope;
  title: string | RichStr;
  /** Shows a close button beside the title. */
  onClose?: () => void;
  /** A chart slice or span that narrows every section. The chart's picker shows and clears it. */
  range?: SliceRange | null;
  /** Drops `range`, from the empty panel's "Past Activities". */
  onClearRange?: () => void;
  /** Keeps the card in view under the page header while the column beside it scrolls. */
  sticky?: boolean;
  /** Counts asks to show the open errors with no index run to focus. Each resets the level, search and connectors as a focus does. */
  errorsRequest?: number;
  className?: string;
  ref?: React.Ref<HTMLDivElement>;
}

/** The scope's runs by level, in sections: open failures, open errors, running, the level's resolved runs a toggle away, then successes and cancels. */
export default function ActivityPanel({
  scope,
  title,
  onClose,
  range = null,
  onClearRange,
  sticky = false,
  errorsRequest = 0,
  className,
  ref,
  ...links
}: ActivityPanelProps) {
  const focusAttemptId = links.focusAttemptId ?? null;
  const focusRequest = links.focusRequest ?? 0;
  const t = useTranslations("admin.connector.activity");
  const tPanel = useTranslations("admin.indexing.activities.panel");
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const [level, setLevel] = useState<ActivityLevel>(DEFAULT_LEVEL);
  const [filtersOpen, setFiltersOpen] = useState(false);
  // Adds the level's resolved and superseded runs under Resolved.
  const [showResolved, setShowResolved] = useState(false);
  const [ccPairIds, setCcPairIds] = useState<number[]>([]);
  // The narrowing and counts the confirm states, fixed when it opens so a search
  // typed meanwhile cannot widen what the click resolves.
  const [confirming, setConfirming] = useState<{
    level: CCPairRunLevel | null;
    statusGroups: CCPairRunStatusGroup[] | null;
    narrowing: ActivityNarrowing;
    failures: number;
    errors: number;
  } | null>(null);
  const confirmModal = useCreateModal();
  const {
    resolving,
    resolve,
    resolveRun,
    resolveWithoutRetry,
    resolveMatching,
  } = useResolveRunErrors();

  // A panel hidden beside the column stays mounted for the stacked layout, so it stops polling until it shows.
  const [displayRef, displayed] = useIsDisplayed<HTMLDivElement>();
  const rootRef = useMemo(() => mergeRefs(ref, displayRef), [ref, displayRef]);
  const pollMs = displayed ? RUNS_POLL_MS : 0;
  // The header counts poll like the feeds and keep the last count while a new range loads, so the tags do not blink.
  const headerCountSwr = { refreshInterval: pollMs, keepPreviousData: true };
  const timeRange = {
    since: range?.since ?? null,
    until: range?.until ?? null,
  };
  const narrowing: ActivityNarrowing = {
    q: search,
    range: timeRange,
    ccPairIds,
  };
  const levelConfig: LevelConfig = LEVELS[level];
  const shownSections = levelConfig.sections;
  const { resolveLevel, errorStatusGroups } = levelConfig;
  const isShown = (section: ActivitySection) => shownSections.includes(section);
  const feed = (
    shown: boolean,
    statusGroups: CCPairRunStatusGroup[] | null = null
  ): ActivityItemsOptions => ({
    enabled: shown,
    pollMs,
    statusGroups,
  });

  // The header counts every open failure and error the search would hide too.
  const unsearched: ActivityNarrowing = { ...narrowing, q: "" };
  const failureCount = useActivityRunsCount(
    scope,
    ["failures"],
    unsearched,
    true,
    headerCountSwr
  );
  const errorCount = useActivityRunsCount(
    scope,
    ["errors"],
    unsearched,
    true,
    headerCountSwr
  );
  const open = {
    failures: useActivityItems(
      scope,
      "failures",
      false,
      narrowing,
      feed(isShown("failures"))
    ),
    errors: useActivityItems(
      scope,
      "errors",
      false,
      narrowing,
      feed(isShown("errors"), errorStatusGroups)
    ),
    running: useActivityItems(
      scope,
      "running",
      false,
      narrowing,
      feed(isShown("running"))
    ),
    success: useActivityItems(
      scope,
      "success",
      false,
      narrowing,
      feed(isShown("success"))
    ),
    canceled: useActivityItems(
      scope,
      "canceled",
      false,
      narrowing,
      feed(isShown("canceled"))
    ),
  };
  // The run count each section's page was last asked at for a focus, so one page loads at a time.
  const focusPagedAt = useRef<Partial<Record<ActivitySection, number>>>({});
  // A focus request names an index run with open failures or errors, and an errors request any open error, so each shows the level, search and connectors that list both open sections, and a focus then pages to its run.
  const revealOpenSections = useEffectEvent(() => {
    focusPagedAt.current = {};
    setLevel((current) => {
      const { sections }: LevelConfig = LEVELS[current];
      return FOCUS_SECTIONS.every((section) => sections.includes(section))
        ? current
        : DEFAULT_LEVEL;
    });
    setSearchInput("");
    setCcPairIds([]);
  });
  useEffect(() => {
    if (focusAttemptId !== null) revealOpenSections();
  }, [focusAttemptId, focusRequest]);
  useEffect(() => {
    if (errorsRequest > 0) revealOpenSections();
  }, [errorsRequest]);
  const focusRevealed =
    FOCUS_SECTIONS.every(isShown) &&
    searchInput === "" &&
    search === "" &&
    ccPairIds.length === 0;
  const focusedPairId =
    [...open.failures.runs, ...open.errors.runs].find(
      ({ run }) => run.kind === "indexing" && run.attempt.id === focusAttemptId
    )?.ccPairId ?? null;
  const focusListed = focusedPairId !== null;
  // A focused card lifts its connector's row like a hovered one, until the focus ends.
  const reportFocusedPair = useEffectEvent((ccPairId: number | null) =>
    links.onFocusPair?.(ccPairId)
  );
  useEffect(() => {
    if (focusedPairId === null) return;
    reportFocusedPair(focusedPairId);
    return () => reportFocusedPair(null);
  }, [focusedPairId]);
  const { failures: openFailures, errors: openErrors } = open;
  const rangeSet = range !== null;
  useEffect(() => {
    if (focusAttemptId === null || focusListed) return;
    // Pages only once the reset above shows the unnarrowed sections, or the page lands on a feed about to start over.
    if (!focusRevealed) return;
    const focusFeeds = [openFailures, openErrors];
    if (focusFeeds.every((focusFeed) => !focusFeed.hasMore)) {
      // Every open run in the chart's span is listed without the focused one, so the span is dropped. A span that lists the run stays.
      const settled = focusFeeds.every(
        (focusFeed) => focusFeed.loaded && !focusFeed.isLoading
      );
      if (rangeSet && settled) {
        focusPagedAt.current = {};
        onClearRange?.();
      }
      return;
    }
    for (const focusFeed of focusFeeds) {
      if (!focusFeed.hasMore) continue;
      if (focusPagedAt.current[focusFeed.section] === focusFeed.runs.length) {
        continue;
      }
      focusPagedAt.current[focusFeed.section] = focusFeed.runs.length;
      focusFeed.more();
    }
  }, [
    focusAttemptId,
    focusListed,
    focusRevealed,
    openFailures,
    openErrors,
    rangeSet,
    onClearRange,
  ]);
  const closed = [
    useActivityItems(
      scope,
      "failures",
      true,
      narrowing,
      feed(showResolved && isShown("failures"))
    ),
    useActivityItems(
      scope,
      "errors",
      true,
      narrowing,
      feed(showResolved && isShown("errors"), errorStatusGroups)
    ),
  ];
  // Only the enabled feeds, since a disabled one never loads and would hold the panel's loading and empty states.
  const resolvedStates = showResolved
    ? closed.filter((state) => isShown(state.section))
    : [];

  // A card with a panel open stays in its section after its last open error resolves there, until the panel closes.
  const {
    sections: heldOpen,
    hold,
    isHeld,
  } = useHeldOpenRun(Object.values(open));
  const resolvedCards = resolvedStates
    .flatMap(sectionCards)
    .filter(({ item }) => !isHeld(item));
  const resolvedKeys = new Set(
    resolvedCards.map(({ item }) => runKey(item.run))
  );
  const openState = (section: ActivitySection): ActivitySectionState =>
    heldOpen.find((state) => state.section === section) ?? open[section];
  // Only Resolved lists a closed run: a resolved run with no error rows also matches a section that resolves nothing, and a search finds superseded runs under their open section too.
  const sectionBlock = (section: ActivitySection): Block => {
    const state = openState(section);
    return {
      key: section,
      title: t(`groups.${section}`, { count: state.total }),
      cards: sectionCards(state).filter(
        ({ item }) => !resolvedKeys.has(runKey(item.run))
      ),
      states: [state],
    };
  };
  const blocks: Block[] = [
    ...shownSections
      .filter((section) => !SETTLED.includes(section))
      .map(sectionBlock),
    {
      key: "resolved",
      title: t("groups.resolved"),
      cards: resolvedCards,
      states: resolvedStates,
    },
    ...shownSections
      .filter((section) => SETTLED.includes(section))
      .map(sectionBlock),
  ];
  const shownStates = blocks.flatMap((block) => block.states);
  const loading = shownStates.some((state) => state.isLoading && !state.loaded);
  const failed = shownStates.some((state) => state.failed);
  const empty = shownStates.every(
    (state) => state.loaded && state.runs.length === 0
  );
  // Older items of the level, asked for only where Past Activities can show: an empty panel narrowed by the range, with the filters folded, since the design draws none beside open filters.
  const pastCount = useActivityRunsCount(
    scope,
    shownSections,
    { ...narrowing, range: { since: null, until: timeRange.since } },
    empty && !loading && !failed && timeRange.since !== null && !filtersOpen,
    {},
    errorStatusGroups
  );

  const canResolveRuns = scope === "fleet" || scope.canResolveRuns;
  const canResolveAll = canResolveRuns && resolveLevel !== undefined;
  const resolvesFailures = canResolveAll && resolveLevel !== "errors";
  const resolvesErrors = canResolveAll && resolveLevel !== "failures";
  const failuresResolvable = useResolvableRunsCount(
    scope,
    resolvesFailures,
    narrowing,
    { level: "failures", statusGroups: null, pollMs }
  );
  const errorsResolvable = useResolvableRunsCount(
    scope,
    resolvesErrors,
    narrowing,
    { level: "errors", statusGroups: errorStatusGroups, pollMs }
  );
  // A disabled count keeps its last value, so only the levels resolved here count.
  const failuresToResolve = resolvesFailures ? failuresResolvable.count : 0;
  const errorsToResolve = resolvesErrors ? errorsResolvable.count : 0;
  const resolveAllCount = failuresToResolve + errorsToResolve;
  // Waits until the counts match the search typed.
  const resolveAllSettled =
    searchInput.trim() === search &&
    !failuresResolvable.isLoading &&
    !errorsResolvable.isLoading;
  const resolveAllEnabled =
    canResolveAll && resolveAllSettled && !resolving && resolveAllCount > 0;
  // Folding keeps the filters, so the toggle reads filled while any is set.
  const filtersActive =
    searchInput.trim() !== "" ||
    level !== DEFAULT_LEVEL ||
    showResolved ||
    ccPairIds.length > 0;
  function filterToggleState(): "selected" | "filled" | "empty" {
    if (filtersOpen) return "selected";
    return filtersActive ? "filled" : "empty";
  }
  const filterToggleLabel = t(
    filtersOpen ? "filter.toggleHide" : "filter.toggleShow"
  );
  const LevelIcon = LEVELS[level].icon;

  return (
    <Section
      ref={rootRef}
      justifyContent="start"
      alignItems="stretch"
      width="full"
      height="fit"
      className={cn(BESIDE.panel, className)}
      data-testid="connector-activity"
      // The stack trace opens beside this edge.
      data-side-panel=""
    >
      <Section
        alignItems="stretch"
        height="fit"
        className={cn(
          "min-h-0",
          BESIDE.panelBody,
          sticky && BESIDE.panelSticky
        )}
      >
        <Card
          border="solid"
          rounding={4}
          padding={2}
          height="full"
          color={
            empty && !loading ? "background-tint-01" : "background-tint-00"
          }
        >
          <Section
            alignItems="stretch"
            gap={2}
            height="fit"
            className="min-h-0"
          >
            <Section alignItems="stretch" gap={1} height="fit">
              <Section
                flexDirection="row"
                justifyContent="between"
                alignItems="center"
                gap={1}
                height="fit"
              >
                <Content
                  icon={SvgActivity}
                  title={title}
                  font="main-ui-action"
                />
                <Section
                  flexDirection="row"
                  justifyContent="end"
                  alignItems="center"
                  gap={1}
                  width="fit"
                  height="fit"
                >
                  <ActivityCountTags
                    failures={failureCount ?? 0}
                    errors={errorCount ?? 0}
                  />
                  <SelectButton
                    icon={SvgFilter}
                    state={filterToggleState()}
                    tooltip={filterToggleLabel}
                    aria-label={filterToggleLabel}
                    onClick={() => setFiltersOpen((shown) => !shown)}
                  />
                  {/* Absent on levels that list nothing open, disabled while nothing shown resolves. */}
                  {canResolveAll && (
                    <Button
                      icon={SvgCheckAll}
                      prominence="tertiary"
                      tooltip={t("resolveAll.button")}
                      aria-label={t("resolveAll.button")}
                      disabled={!resolveAllEnabled}
                      onClick={() => {
                        setConfirming({
                          level: resolveLevel ?? null,
                          statusGroups: errorStatusGroups,
                          narrowing,
                          failures: failuresToResolve,
                          errors: errorsToResolve,
                        });
                        confirmModal.toggle(true);
                      }}
                    />
                  )}
                  {onClose !== undefined && (
                    <Button
                      icon={SvgFold}
                      prominence="tertiary"
                      tooltip={tPanel("close")}
                      tooltipSide="start"
                      aria-label={tPanel("close")}
                      onClick={onClose}
                    />
                  )}
                </Section>
              </Section>
              {filtersOpen && (
                <>
                  <Section
                    flexDirection="row"
                    alignItems="center"
                    gap={1}
                    height="fit"
                  >
                    <Section
                      alignItems="stretch"
                      height="fit"
                      className="min-w-[10rem] flex-1"
                    >
                      <InputTypeIn
                        icon="search"
                        placeholder={t("search.placeholder")}
                        maxLength={SEARCH_MAX_LENGTH}
                        value={searchInput}
                        onChange={(event) => setSearchInput(event.target.value)}
                      />
                    </Section>
                    <SelectButton
                      variant="select-filter"
                      icon={showResolved ? SvgEye : SvgEyeClosed}
                      state={showResolved ? "selected" : "empty"}
                      onClick={() => setShowResolved((value) => !value)}
                    >
                      {t("filter.resolved")}
                    </SelectButton>
                  </Section>
                  <Section
                    flexDirection="row"
                    justifyContent="start"
                    gap={1}
                    height="fit"
                    wrap
                  >
                    <Dropdown>
                      <Dropdown.Trigger asChild>
                        <SelectButton
                          variant="select-filter"
                          chevron
                          labelFont="main-ui-action"
                          icon={LevelIcon}
                          state={
                            level !== DEFAULT_LEVEL ? "selected" : "filled"
                          }
                        >
                          {t(`filter.${level}`)}
                        </SelectButton>
                      </Dropdown.Trigger>
                      <Dropdown.Data
                        label={t("filter.label")}
                        value={level}
                        onSelect={(option) =>
                          setLevel(
                            LEVEL_ORDER.find(
                              (candidate) => candidate === option.value
                            ) ?? DEFAULT_LEVEL
                          )
                        }
                        items={LEVEL_ORDER.map((candidate) => ({
                          kind: "option" as const,
                          value: candidate,
                          title: t(`filter.${candidate}`),
                          icon: LEVELS[candidate].icon,
                        }))}
                      />
                    </Dropdown>
                    {scope === "fleet" && (
                      <ConnectorsFilter
                        value={ccPairIds}
                        onChange={setCcPairIds}
                      />
                    )}
                  </Section>
                </>
              )}
            </Section>

            <ShadowDiv shadowHeight={4}>
              <Section
                alignItems="stretch"
                gap={2}
                height="fit"
                className="mt-1"
              >
                {failed ? (
                  <MessageCard variant="error" title={t("loadError.title")} />
                ) : loading ? (
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
                ) : empty ? (
                  <>
                    {/* The design insets the illustration 24 above and 28 below, 4 and 8 past IllustrationContent's own 20. */}
                    <Section height="fit" className="mt-1 mb-2">
                      <IllustrationContent
                        size="sm"
                        illustration={SvgLongWait}
                        title={
                          search !== "" ? t("empty.filtered") : t("empty.title")
                        }
                      />
                    </Section>
                    {pastCount !== null &&
                      pastCount > 0 && (
                        // Opens nothing in place: it widens the time filter so the older runs list.
                        <Divider
                          title={t("empty.past")}
                          foldable
                          chevronPosition="start"
                          foldedChevron="down"
                          open={false}
                          onOpenChange={() => onClearRange?.()}
                        />
                      )}
                  </>
                ) : (
                  // A block whose loaded cards all repeat under Resolved keeps its "more", so older runs stay reachable.
                  blocks
                    .filter(
                      (block) =>
                        block.cards.length > 0 ||
                        block.states.some((state) => state.hasMore)
                    )
                    .map((block) => (
                      <BlockList
                        key={block.key}
                        block={block}
                        resolving={resolving}
                        onResolve={(item, errorIds) =>
                          void resolve(item, errorIds)
                        }
                        onResolveWithoutRetry={(item, errorIds, route) =>
                          resolveWithoutRetry(item.ccPairId, errorIds, route)
                        }
                        onResolveRun={(item) => void resolveRun(item)}
                        links={links}
                        onPanelOpenChange={(item, section, open) =>
                          hold(section, item, open)
                        }
                      />
                    ))
                )}
              </Section>
            </ShadowDiv>
          </Section>
        </Card>
      </Section>
      <confirmModal.Provider>
        {confirming !== null && (
          <ConfirmationModalLayout
            icon={SvgCheckAll}
            title={t("resolveAll.title")}
            onClose={() => confirmModal.toggle(false)}
            submit={
              <Button
                disabled={resolving}
                onClick={async () => {
                  await resolveMatching(scope, confirming.narrowing, {
                    level: confirming.level,
                    statusGroups: confirming.statusGroups,
                  });
                  confirmModal.toggle(false);
                }}
              >
                {t("resolveAll.confirm")}
              </Button>
            }
          >
            <Section alignItems="stretch" gap={2} height="fit">
              <Text as="p" font="main-ui-body" color="text-03">
                {t("resolveAll.body", {
                  count: confirming.failures + confirming.errors,
                  failures: t("resolveAll.failures", {
                    count: confirming.failures,
                  }),
                  errors: t("resolveAll.errors", { count: confirming.errors }),
                })}
              </Text>
              <Text as="p" font="main-ui-body" color="text-03">
                {t("resolveAll.body2")}
              </Text>
            </Section>
          </ConfirmationModalLayout>
        )}
      </confirmModal.Provider>
    </Section>
  );
}
