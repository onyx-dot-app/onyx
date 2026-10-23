"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  Dropdown,
  FilterButton,
  InputTypeIn,
  MessageCard,
  SelectButton,
  ShadowDiv,
  Tag,
} from "@opal/components";
import { useDebouncedValue } from "@opal/hooks";
import {
  ConfirmationModalLayout,
  Content,
  IllustrationContent,
  Section,
} from "@opal/layouts";
import { SvgLongWait } from "@opal/illustrations";
import { CardLoader } from "@opal/loaders";
import {
  SvgActivity,
  SvgAlertTriangle,
  SvgCheckAll,
  SvgEye,
  SvgEyeClosed,
  SvgFilter,
  SvgFold,
  SvgXOctagon,
} from "@opal/icons";
import type { RichStr } from "@opal/types";
import { cn } from "@opal/utils";
import {
  useActivityItems,
  useResolvableRunsCount,
  useResolveRunErrors,
  type ActivityGroup,
  type ActivityGroupState,
  type ActivityItem,
  type ActivityScope,
  type ActivityTimeRange,
} from "@/lib/connectors/ccPair/hooks";
import type { CCPairRunLevel } from "@/lib/connectors/types";
import ActivityCard from "@/views/admin/connectors/ConnectorDetailPage/ActivityCard";
import {
  RUNS_POLL_MS,
  SEARCH_DELAY_MS,
  SEARCH_MAX_LENGTH,
} from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import type { SliceRange } from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

const LOADER_ROWS = 2;

/** Which levels the filter shows. */
type Shown = "all" | ActivityGroup;

export interface ActivityCountTagsProps {
  failures: number;
  errors: number;
  /** `"count"` drops the tinted backgrounds, for a card header. Default: `"status"`. */
  variant?: "status" | "count";
}
/** The failed runs and the runs with document errors, as two counts. A zero count shows no tag. */
export function ActivityCountTags({
  failures,
  errors,
  variant = "status",
}: ActivityCountTagsProps) {
  const t = useTranslations("admin.connector.activity");
  const format = useFormatter();
  return (
    <>
      {failures > 0 && (
        <Tag
          icon={SvgXOctagon}
          title={format.number(failures)}
          tooltip={t("counts.failures", { count: failures })}
          color="red"
          variant={variant}
          size="md"
        />
      )}
      {errors > 0 && (
        <Tag
          icon={SvgAlertTriangle}
          title={format.number(errors)}
          tooltip={t("counts.errors", { count: errors })}
          color="orange"
          variant={variant}
          size="md"
        />
      )}
    </>
  );
}

interface GroupListProps {
  state: ActivityGroupState;
  /** The runs are the level's resolved ones. */
  closed: boolean;
  resolving: boolean;
  onResolve: (item: ActivityItem, errorIds: number[] | null) => void;
  onResolveRun: (item: ActivityItem) => void;
}
function GroupList({
  state,
  closed,
  resolving,
  onResolve,
  onResolveRun,
}: GroupListProps) {
  const t = useTranslations("admin.connector.activity");
  if (state.runs.length === 0) return null;
  return (
    <Section alignItems="stretch" gap={1} height="fit">
      <Divider title={t(`groups.${state.group}`, { count: state.total })} />
      {state.runs.map((item) => (
        <ActivityCard
          key={`${item.run.kind}-${item.run.attempt.id}`}
          ccPairId={item.ccPairId}
          run={item.run}
          group={state.group}
          closed={closed}
          connector={item.connector}
          canResolve={item.canResolve}
          canResolveRuns={item.canResolveRuns}
          resolving={resolving}
          onResolve={(errorIds) => onResolve(item, errorIds)}
          onResolveRun={() => onResolveRun(item)}
        />
      ))}
      {state.hasMore && (
        <Section alignItems="center" height="fit">
          <Button prominence="tertiary" size="xs" onClick={state.more}>
            {t("more")}
          </Button>
        </Section>
      )}
    </Section>
  );
}

export interface ActivityPanelProps {
  /** One pair's runs, or every readable pair's. */
  scope: ActivityScope;
  title: string | RichStr;
  /** Shows a close button beside the title. */
  onClose?: () => void;
  /** Folds the search and filters behind a header button, so the run list leads the card. The header then holds the counts and Resolve All. */
  foldFilters?: boolean;
  /** A chart slice or span that narrows every group. The chart's picker shows and clears it. */
  range?: SliceRange | null;
  /** Keeps the card in view under the page header while the column beside it scrolls. */
  sticky?: boolean;
  className?: string;
  ref?: React.Ref<HTMLDivElement>;
}

/** The scope's failed runs and runs with document errors, newest first, with each level's resolved runs a toggle away in their place, and every other run too for the fleet. */
export default function ActivityPanel({
  scope,
  title,
  onClose,
  foldFilters = false,
  range = null,
  sticky = false,
  className,
  ref,
}: ActivityPanelProps) {
  const t = useTranslations("admin.connector.activity");
  const tPanel = useTranslations("admin.indexing.activities.panel");
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const [shown, setShown] = useState<Shown>("all");
  const [filtersOpen, setFiltersOpen] = useState(!foldFilters);
  // Shows each level's resolved and superseded runs in place of its open ones.
  const [showResolved, setShowResolved] = useState(false);
  // The filter and count the confirm states, fixed when it opens so a search
  // typed meanwhile cannot widen what the click resolves.
  const [confirmingResolveAll, setConfirmingResolveAll] = useState<{
    level: CCPairRunLevel | null;
    q: string;
    timeRange: ActivityTimeRange;
    count: number;
  } | null>(null);
  const { resolving, resolve, resolveRun, resolveMatching } =
    useResolveRunErrors();
  // The fleet panel lists every run. A pair's page has its run list for that.
  const shownOptions: Shown[] =
    scope === "fleet"
      ? ["all", "failures", "errors", "other"]
      : ["all", "failures", "errors"];
  const isShown = (group: ActivityGroup) =>
    shownOptions.includes(group) && (shown === "all" || shown === group);

  const timeRange: ActivityTimeRange = {
    since: range?.since ?? null,
    until: range?.until ?? null,
  };
  // The failures and errors totals head the panel, so both always poll.
  const failures = useActivityItems(
    scope,
    "failures",
    false,
    search,
    true,
    RUNS_POLL_MS,
    timeRange
  );
  const closedFailures = useActivityItems(
    scope,
    "failures",
    true,
    search,
    showResolved && isShown("failures"),
    RUNS_POLL_MS,
    timeRange
  );
  const errors = useActivityItems(
    scope,
    "errors",
    false,
    search,
    true,
    RUNS_POLL_MS,
    timeRange
  );
  const closedErrors = useActivityItems(
    scope,
    "errors",
    true,
    search,
    showResolved && isShown("errors"),
    RUNS_POLL_MS,
    timeRange
  );
  const other = useActivityItems(
    scope,
    "other",
    false,
    search,
    !showResolved && isShown("other"),
    RUNS_POLL_MS,
    timeRange
  );
  // The fleet's other runs are never resolved, so the resolved view has no level for them.
  const groups = [
    showResolved ? closedFailures : failures,
    showResolved ? closedErrors : errors,
    ...(showResolved ? [] : [other]),
  ].filter((group) => isShown(group.group));
  const loading = groups.some((group) => group.isLoading && !group.loaded);
  const failed = groups.some((group) => group.failed);
  const empty = groups.every(
    (group) => group.loaded && group.runs.length === 0
  );
  // Resolves the open runs of the levels shown, as the search narrows them.
  const resolveAllLevel: CCPairRunLevel | null =
    shown === "failures" || shown === "errors" ? shown : null;
  const canResolveRuns = scope === "fleet" || scope.canResolveRuns;
  const canResolveAll = !showResolved && shown !== "other" && canResolveRuns;
  const resolvableLevels =
    resolveAllLevel === null
      ? [failures, errors]
      : [{ failures, errors }[resolveAllLevel]];
  const resolvable = useResolvableRunsCount(
    scope,
    canResolveAll,
    resolveAllLevel,
    search,
    timeRange,
    RUNS_POLL_MS
  );
  // Waits until the lists and count match the search typed.
  const resolveAllSettled =
    searchInput.trim() === search &&
    !resolvable.isLoading &&
    resolvableLevels.every((level) => !level.isLoading);
  function emptyTitle(): string {
    if (search !== "" || range !== null) return t("empty.filtered");
    if (showResolved) return t("empty.resolved");
    return shown === "all" ? t("empty.title") : t(`empty.${shown}`);
  }

  const resolveAllBlocked = resolving || !resolveAllSettled;
  // Folding keeps the filters, so the toggle reads filled while any is set.
  const filtersActive =
    searchInput.trim() !== "" || shown !== "all" || showResolved;
  function filterToggleState(): "selected" | "filled" | "empty" {
    if (filtersOpen) return "selected";
    return filtersActive ? "filled" : "empty";
  }
  function confirmResolveAll() {
    setConfirmingResolveAll({
      level: resolveAllLevel,
      q: search,
      timeRange,
      count: resolvable.count,
    });
  }

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
        "lg:max-w-104 lg:shrink-0 lg:h-auto lg:self-stretch lg:contain-size",
        className
      )}
      data-testid="connector-activity"
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
        <Card border="solid" rounding={4} padding={2} height="full">
          <Section
            alignItems="stretch"
            gap={3}
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
                  {foldFilters && (
                    <>
                      <ActivityCountTags
                        failures={failures.total}
                        errors={errors.total}
                        variant="count"
                      />
                      <SelectButton
                        icon={SvgFilter}
                        state={filterToggleState()}
                        size="md"
                        tooltip={t("filter.toggle")}
                        aria-label={t("filter.toggle")}
                        onClick={() => setFiltersOpen((open) => !open)}
                      />
                      {/* The header keeps its action in place and disables it whenever nothing shown can be resolved. */}
                      {canResolveRuns && (
                        <Button
                          icon={SvgCheckAll}
                          prominence="tertiary"
                          tooltip={t("resolveAll.button")}
                          aria-label={t("resolveAll.button")}
                          disabled={
                            !canResolveAll ||
                            resolveAllBlocked ||
                            resolvable.count === 0
                          }
                          onClick={confirmResolveAll}
                        />
                      )}
                    </>
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
                  <InputTypeIn
                    searchIcon
                    variant={foldFilters ? "internal" : "primary"}
                    placeholder={t("search.placeholder")}
                    maxLength={SEARCH_MAX_LENGTH}
                    value={searchInput}
                    onChange={(event) => setSearchInput(event.target.value)}
                  />
                  <Section
                    flexDirection="row"
                    justifyContent="between"
                    alignItems="center"
                    gap={1}
                    height="fit"
                  >
                    {/* The filters shrink and wrap before the counts, so a narrow panel never clips the counts. */}
                    <Section
                      flexDirection="row"
                      justifyContent="start"
                      gap={1}
                      height="fit"
                      wrap
                    >
                      <Dropdown>
                        <Dropdown.Trigger asChild>
                          <FilterButton
                            icon={SvgActivity}
                            active={shown !== "all"}
                            onClear={() => setShown("all")}
                          >
                            {t(`filter.${shown}`)}
                          </FilterButton>
                        </Dropdown.Trigger>
                        <Dropdown.Data
                          label={t("filter.label")}
                          value={shown}
                          onSelect={(option) =>
                            setShown(
                              shownOptions.find(
                                (candidate) => candidate === option.value
                              ) ?? "all"
                            )
                          }
                          items={shownOptions.map((candidate) => ({
                            kind: "option" as const,
                            value: candidate,
                            title: t(`filter.${candidate}`),
                          }))}
                        />
                      </Dropdown>
                      <SelectButton
                        variant="select-filter"
                        icon={showResolved ? SvgEye : SvgEyeClosed}
                        state={showResolved ? "selected" : "empty"}
                        onClick={() => setShowResolved((value) => !value)}
                      >
                        {t("filter.resolved")}
                      </SelectButton>
                      {!foldFilters &&
                        canResolveAll &&
                        resolvable.count > 0 && (
                          <Button
                            rightIcon={SvgCheckAll}
                            prominence="tertiary"
                            disabled={resolveAllBlocked}
                            onClick={confirmResolveAll}
                          >
                            {t("resolveAll.button")}
                          </Button>
                        )}
                    </Section>
                    {!foldFilters && (
                      <Section
                        flexDirection="row"
                        justifyContent="end"
                        gap={0.5}
                        width="fit"
                        height="fit"
                      >
                        <ActivityCountTags
                          failures={failures.total}
                          errors={errors.total}
                        />
                      </Section>
                    )}
                  </Section>
                </>
              )}
            </Section>

            <ShadowDiv shadowHeight={4}>
              <Section alignItems="stretch" gap={3} height="fit">
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
                  <IllustrationContent
                    illustration={SvgLongWait}
                    title={emptyTitle()}
                  />
                ) : (
                  groups.map((group) => (
                    <GroupList
                      key={group.group}
                      state={group}
                      closed={showResolved}
                      resolving={resolving}
                      onResolve={(item, errorIds) =>
                        void resolve(item, errorIds)
                      }
                      onResolveRun={(item) => void resolveRun(item)}
                    />
                  ))
                )}
              </Section>
            </ShadowDiv>
          </Section>
        </Card>
      </Section>
      {confirmingResolveAll !== null && (
        <ConfirmationModalLayout
          icon={SvgCheckAll}
          title={t("resolveAll.title")}
          onClose={() => setConfirmingResolveAll(null)}
          submit={
            <Button
              onClick={() => {
                setConfirmingResolveAll(null);
                void resolveMatching(
                  scope,
                  confirmingResolveAll.level,
                  confirmingResolveAll.q,
                  confirmingResolveAll.timeRange
                );
              }}
            >
              {t("resolveAll.confirm")}
            </Button>
          }
        >
          {scope === "fleet"
            ? t("resolveAll.fleetDescription", {
                count: confirmingResolveAll.count,
              })
            : t("resolveAll.description", {
                count: confirmingResolveAll.count,
              })}
        </ConfirmationModalLayout>
      )}
    </Section>
  );
}
