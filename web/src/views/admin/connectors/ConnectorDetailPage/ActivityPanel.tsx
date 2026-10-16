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
  Tag,
} from "@opal/components";
import { useDebouncedValue } from "@opal/hooks";
import { Content, IllustrationContent, Section } from "@opal/layouts";
import { CardLoader } from "@opal/loaders";
import {
  SvgActivity,
  SvgAlertTriangle,
  SvgEyeClosed,
  SvgFold,
  SvgXCircle,
} from "@opal/icons";
import type { RichStr } from "@opal/types";
import { cn } from "@opal/utils";
import {
  useActivityItems,
  useResolveRunErrors,
  type ActivityGroup,
  type ActivityGroupState,
  type ActivityItem,
  type ActivityScope,
  type ActivityTimeRange,
} from "@/lib/connectors/ccPair/hooks";
import ActivityCard from "@/views/admin/connectors/ConnectorDetailPage/ActivityCard";
import {
  RUNS_POLL_MS,
  SEARCH_DELAY_MS,
  SEARCH_MAX_LENGTH,
} from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import {
  SliceRangeFilter,
  type SliceRange,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

const LOADER_ROWS = 2;

/** Which groups the filter shows. Resolved runs replace them all when toggled on. */
type Shown = "all" | "failures" | "errors" | "other";

export interface ActivityCountTagsProps {
  failures: number;
  errors: number;
}
/** The failed runs and the runs with document errors, as two counts. */
export function ActivityCountTags({
  failures,
  errors,
}: ActivityCountTagsProps) {
  const t = useTranslations("admin.connector.activity");
  const format = useFormatter();
  return (
    <>
      <Tag
        icon={SvgXCircle}
        title={format.number(failures)}
        tooltip={t("counts.failures", { count: failures })}
        color="red"
      />
      <Tag
        icon={SvgAlertTriangle}
        title={format.number(errors)}
        tooltip={t("counts.errors", { count: errors })}
        color="amber"
      />
    </>
  );
}

interface GroupListProps {
  state: ActivityGroupState;
  resolving: boolean;
  onResolve: (item: ActivityItem, errorIds: number[] | null) => void;
}
function GroupList({ state, resolving, onResolve }: GroupListProps) {
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
          connector={item.connector}
          canResolve={item.canResolve}
          resolving={resolving}
          onResolve={(errorIds) => onResolve(item, errorIds)}
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
  /** A chart slice that narrows every group, shown as a filter its `onClearRange` removes. */
  range?: SliceRange | null;
  onClearRange?: () => void;
  className?: string;
}

/** The scope's failed runs and runs with document errors, newest first, with the resolved ones a filter away, and every other run too for the fleet. */
export default function ActivityPanel({
  scope,
  title,
  onClose,
  range = null,
  onClearRange,
  className,
}: ActivityPanelProps) {
  const t = useTranslations("admin.connector.activity");
  const tPanel = useTranslations("admin.indexing.activities.panel");
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const [shown, setShown] = useState<Shown>("all");
  const [resolved, setResolved] = useState(false);
  const { resolving, resolve } = useResolveRunErrors();
  // The fleet panel lists every run. A pair's page has its run list for that.
  const shownOptions: Shown[] =
    scope === "fleet"
      ? ["all", "failures", "errors", "other"]
      : ["all", "failures", "errors"];
  const isShown = (group: ActivityGroup) =>
    group === "resolved"
      ? resolved
      : !resolved &&
        shownOptions.includes(group) &&
        (shown === "all" || shown === group);

  const timeRange: ActivityTimeRange = {
    since: range?.since ?? null,
    until: range?.until ?? null,
  };
  // The failures and errors totals head the panel, so both always poll.
  const failures = useActivityItems(
    scope,
    "failures",
    search,
    true,
    RUNS_POLL_MS,
    timeRange
  );
  const errors = useActivityItems(
    scope,
    "errors",
    search,
    true,
    RUNS_POLL_MS,
    timeRange
  );
  const other = useActivityItems(
    scope,
    "other",
    search,
    isShown("other"),
    RUNS_POLL_MS,
    timeRange
  );
  const resolvedRuns = useActivityItems(
    scope,
    "resolved",
    search,
    isShown("resolved"),
    RUNS_POLL_MS,
    timeRange
  );
  const groups = [failures, errors, other, resolvedRuns].filter((group) =>
    isShown(group.group)
  );
  const loading = groups.some((group) => group.isLoading && !group.loaded);
  const failed = groups.some((group) => group.failed);
  const empty = groups.every(
    (group) => group.loaded && group.runs.length === 0
  );
  const emptyTitle =
    search !== "" || range !== null
      ? t("empty.filtered")
      : resolved
        ? t("empty.resolved")
        : shown === "all"
          ? t("empty.title")
          : t(`empty.${shown}`);

  // Full width once the page stacks its columns, the panel's own width beside them.
  return (
    <Section
      alignItems="stretch"
      width="full"
      height="fit"
      className={cn("lg:max-w-104 lg:shrink-0", className)}
      data-testid="connector-activity"
    >
      <Card border="solid" rounding={4} padding={2}>
        <Section alignItems="stretch" gap={3} height="fit">
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
                  variant="internal"
                  placeholder={t("search.placeholder")}
                  maxLength={SEARCH_MAX_LENGTH}
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                />
              </Section>
              <Section
                flexDirection="row"
                justifyContent="end"
                gap={2}
                padding={1.5}
                width="fit"
                height="fit"
              >
                {range !== null && onClearRange !== undefined && (
                  <SliceRangeFilter range={range} onClear={onClearRange} />
                )}
                <ActivityCountTags
                  failures={failures.total}
                  errors={errors.total}
                />
              </Section>
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
                icon={SvgEyeClosed}
                state={resolved ? "selected" : "empty"}
                aria-pressed={resolved}
                onClick={() => setResolved((current) => !current)}
              >
                {t("resolved.label")}
              </SelectButton>
            </Section>
          </Section>

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
            <IllustrationContent title={emptyTitle} />
          ) : (
            groups.map((group) => (
              <GroupList
                key={group.group}
                state={group}
                resolving={resolving}
                onResolve={(item, errorIds) => void resolve(item, errorIds)}
              />
            ))
          )}
        </Section>
      </Card>
    </Section>
  );
}
