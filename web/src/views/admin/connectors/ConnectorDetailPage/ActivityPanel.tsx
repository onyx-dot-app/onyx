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
  /** A heading above the search. */
  title?: string | RichStr;
  /** Shows a close button beside the title. */
  onClose?: () => void;
  /** A chart slice or span that narrows every group. The chart's picker shows and clears it. */
  range?: SliceRange | null;
  className?: string;
}

/** The scope's failed runs and runs with document errors, newest first, with each level's resolved runs a toggle away in their place, and every other run too for the fleet. */
export default function ActivityPanel({
  scope,
  title,
  onClose,
  range = null,
  className,
}: ActivityPanelProps) {
  const t = useTranslations("admin.connector.activity");
  const tPanel = useTranslations("admin.indexing.activities.panel");
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const [shown, setShown] = useState<Shown>("all");
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
  const canResolveAll =
    !showResolved &&
    shown !== "other" &&
    (scope === "fleet" || scope.canResolveRuns);
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

  const countTags = (
    <Section
      flexDirection="row"
      justifyContent="end"
      gap={0.5}
      padding={title === undefined ? 1.5 : 0}
      width="fit"
      height="fit"
    >
      <ActivityCountTags failures={failures.total} errors={errors.total} />
    </Section>
  );

  // Beside the main column the panel pins under the settings header and
  // scrolls inside its own height, so a long list never lengthens the page.
  return (
    <Section
      alignItems="stretch"
      width="full"
      height="fit"
      className={cn(
        "lg:max-w-104 lg:shrink-0 lg:sticky lg:top-[calc(var(--settings-header-height,0px)_+_1.5rem)] lg:max-h-[calc(var(--settings-scroll-height,100dvh)_-_var(--settings-header-height,0px)_-_6rem)]",
        className
      )}
      data-testid="connector-activity"
    >
      <Card border="solid" rounding={4} padding={2} height="full">
        <Section alignItems="stretch" gap={3} height="fit" className="min-h-0">
          <Section alignItems="stretch" gap={1} height="fit">
            {title !== undefined && (
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
                {onClose !== undefined && (
                  <Button
                    icon={SvgFold}
                    prominence="tertiary"
                    tooltip={tPanel("close")}
                    aria-label={tPanel("close")}
                    onClick={onClose}
                  />
                )}
              </Section>
            )}
            {/* Beside the page the search shares its row with the counts. The side panel gives the search its own row. */}
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="center"
              gap={1}
              height="fit"
            >
              <Section height="fit" className="min-w-0 flex-1">
                <InputTypeIn
                  searchIcon
                  variant={title === undefined ? "internal" : "primary"}
                  placeholder={t("search.placeholder")}
                  maxLength={SEARCH_MAX_LENGTH}
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                />
              </Section>
              {title === undefined && countTags}
            </Section>
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="center"
              gap={1}
              height="fit"
            >
              <Section
                flexDirection="row"
                justifyContent="start"
                gap={1}
                width="fit"
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
                {canResolveAll && resolvable.count > 0 && (
                  <Button
                    rightIcon={SvgCheckAll}
                    prominence="tertiary"
                    disabled={resolving || !resolveAllSettled}
                    onClick={() =>
                      setConfirmingResolveAll({
                        level: resolveAllLevel,
                        q: search,
                        timeRange,
                        count: resolvable.count,
                      })
                    }
                  >
                    {t("resolveAll.button")}
                  </Button>
                )}
              </Section>
              {title !== undefined && countTags}
            </Section>
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
                    onResolve={(item, errorIds) => void resolve(item, errorIds)}
                    onResolveRun={(item) => void resolveRun(item)}
                  />
                ))
              )}
            </Section>
          </ShadowDiv>
        </Section>
      </Card>
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
