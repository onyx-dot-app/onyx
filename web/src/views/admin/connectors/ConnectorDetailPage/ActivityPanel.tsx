"use client";

import { useEffect, useRef, useState } from "react";
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
  Tooltip,
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
import { getSourceMetadata } from "@/lib/connectors/utils";
import ActivityCard from "@/views/admin/connectors/ConnectorDetailPage/ActivityCard";
import { isActive } from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import {
  RUNS_POLL_MS,
  SEARCH_DELAY_MS,
  SEARCH_MAX_LENGTH,
} from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import type { SliceRange } from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

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
  /** The batch resolve's level: null for every resolvable section, undefined where the batch routes, which take a level and no status, cannot narrow to it. */
  resolveLevel: CCPairRunLevel | null | undefined;
  /** Narrows the Errors section's status groups, null for all of them. */
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
    resolveLevel: undefined,
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
// The header counts poll like the feeds and keep the last count while a new range loads, so the tags do not blink.
const HEADER_COUNT_SWR = {
  refreshInterval: RUNS_POLL_MS,
  keepPreviousData: true,
};

// Finished runs with nothing to resolve list after Resolved. Running runs, which can still report errors, list before it.
const SETTLED: ActivitySection[] = ["success", "canceled"];

export interface ActivityCountTagsProps {
  failures: number;
  errors: number;
}
/** The failed runs and the runs with document errors, as two counts. A zero count shows no tag. */
export function ActivityCountTags({
  failures,
  errors,
}: ActivityCountTagsProps) {
  const t = useTranslations("admin.connector.activity");
  const format = useFormatter();
  return (
    <>
      {failures > 0 && (
        <Tooltip tooltip={t("counts.failures", { count: failures })} side="top">
          <Badge
            icon={SvgXOctagon}
            title={format.number(failures)}
            color="error"
            textColor="text-04"
            size={6}
          />
        </Tooltip>
      )}
      {errors > 0 && (
        <Tooltip tooltip={t("counts.errors", { count: errors })} side="top">
          <Badge
            icon={SvgAlertTriangle}
            title={format.number(errors)}
            color="warning"
            textColor="text-04"
            size={6}
          />
        </Tooltip>
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
    errorIds: number[]
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
  const { onHoverAttempt, focusAttemptId = null, outlinedAttemptIds } = links;
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
            onResolveWithoutRetry={(errorIds) =>
              onResolveWithoutRetry(item, errorIds)
            }
            onResolveRun={() => onResolveRun(item)}
            onPanelOpenChange={
              closed
                ? undefined
                : (open) => onPanelOpenChange(item, section, open)
            }
            onHoverChange={
              charted && onHoverAttempt !== undefined
                ? (hovered) => onHoverAttempt(hovered ? attempt.id : null)
                : undefined
            }
            focused={charted && focusAttemptId === attempt.id}
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
  className,
  ref,
  onHoverAttempt,
  focusAttemptId = null,
  outlinedAttemptIds = [],
}: ActivityPanelProps) {
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
    narrowing: ActivityNarrowing;
    failures: number;
    errors: number;
  } | null>(null);
  const {
    resolving,
    resolve,
    resolveRun,
    resolveWithoutRetry,
    resolveMatching,
  } = useResolveRunErrors();

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
    pollMs: RUNS_POLL_MS,
    statusGroups,
  });

  // The header counts every open failure and error the search would hide too.
  const unsearched: ActivityNarrowing = { ...narrowing, q: "" };
  const failureCount = useActivityRunsCount(
    scope,
    ["failures"],
    unsearched,
    true,
    HEADER_COUNT_SWR
  );
  const errorCount = useActivityRunsCount(
    scope,
    ["errors"],
    unsearched,
    true,
    HEADER_COUNT_SWR
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
  // The run count a page was last asked at for a focus, so one page loads at a time.
  const focusPagedAt = useRef<number | null>(null);
  // A failure line names an open failed index run, so its focus shows the level, search and connectors that list it, then pages to it.
  useEffect(() => {
    if (focusAttemptId === null) return;
    focusPagedAt.current = null;
    setLevel((current) => {
      const { sections }: LevelConfig = LEVELS[current];
      return sections.includes("failures") ? current : DEFAULT_LEVEL;
    });
    setSearchInput("");
    setCcPairIds([]);
  }, [focusAttemptId]);
  const focusFeed = open.failures;
  const focusRevealed =
    isShown("failures") &&
    searchInput === "" &&
    search === "" &&
    ccPairIds.length === 0;
  const focusListed = focusFeed.runs.some(
    ({ run }) => run.kind === "indexing" && run.attempt.id === focusAttemptId
  );
  const rangeSet = range !== null;
  useEffect(() => {
    if (focusAttemptId === null || focusListed) return;
    // Pages only once the reset above shows the unnarrowed failures, or the page lands on a feed about to start over.
    if (!focusRevealed) return;
    if (!focusFeed.hasMore) {
      // Every failure in the chart's span is listed without the run, so the span is dropped. A span that lists the run stays.
      if (rangeSet && focusFeed.loaded && !focusFeed.isLoading) {
        focusPagedAt.current = null;
        onClearRange?.();
      }
      return;
    }
    if (focusPagedAt.current === focusFeed.runs.length) return;
    focusPagedAt.current = focusFeed.runs.length;
    focusFeed.more();
  }, [
    focusAttemptId,
    focusListed,
    focusFeed,
    focusRevealed,
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
  const failuresResolvable = useResolvableRunsCount(
    scope,
    canResolveAll,
    "failures",
    narrowing,
    RUNS_POLL_MS
  );
  const errorsResolvable = useResolvableRunsCount(
    scope,
    canResolveAll && resolveLevel === null,
    "errors",
    narrowing,
    RUNS_POLL_MS
  );
  const errorsToResolve = resolveLevel === null ? errorsResolvable.count : 0;
  const resolveAllCount = failuresResolvable.count + errorsToResolve;
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
  const links = { onHoverAttempt, focusAttemptId, outlinedAttemptIds };
  const LevelIcon = LEVELS[level].icon;

  // Beside the main column the panel stretches to the column's height under size
  // containment, so a long list scrolls inside the card and a short one stays short.
  return (
    <Section
      ref={ref}
      justifyContent="start"
      alignItems="stretch"
      width="full"
      height="fit"
      className={cn(
        "lg:w-100 lg:shrink-0 lg:h-auto lg:self-stretch lg:contain-size",
        className
      )}
      data-testid="connector-activity"
      // The stack trace opens beside this edge.
      data-side-panel=""
    >
      {/* 1.5rem and 6rem match SettingsLayouts.Body's pt-6 and pt-6 + pb-18, so the page's end never pushes the title out of view. */}
      <Section
        alignItems="stretch"
        height="fit"
        className={cn(
          "min-h-0 lg:max-h-full",
          sticky &&
            "lg:sticky lg:top-[calc(var(--settings-header-height,0px)_+_1.5rem)] lg:max-h-[min(100%,calc(var(--settings-scroll-height)_-_var(--settings-header-height,0px)_-_6rem))]"
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
                  sizePreset="main-ui"
                  variant="section"
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
                  {/* Absent on levels the batch routes cannot narrow to, disabled while nothing shown resolves. */}
                  {canResolveAll && (
                    <Button
                      icon={SvgCheckAll}
                      prominence="tertiary"
                      tooltip={t("resolveAll.button")}
                      aria-label={t("resolveAll.button")}
                      disabled={!resolveAllEnabled}
                      onClick={() =>
                        setConfirming({
                          level: resolveLevel ?? null,
                          narrowing,
                          failures: failuresResolvable.count,
                          errors: errorsToResolve,
                        })
                      }
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
                        onResolveWithoutRetry={(item, errorIds) =>
                          resolveWithoutRetry(item.ccPairId, errorIds)
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
      {confirming !== null && (
        <ConfirmationModalLayout
          icon={SvgCheckAll}
          title={t("resolveAll.title")}
          onClose={() => setConfirming(null)}
          submit={
            <Button
              disabled={resolving}
              onClick={async () => {
                await resolveMatching(
                  scope,
                  confirming.level,
                  confirming.narrowing
                );
                setConfirming(null);
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
    </Section>
  );
}
