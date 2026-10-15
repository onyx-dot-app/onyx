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
import { CardLoader } from "@opal/loaders";
import {
  SvgActivity,
  SvgAlertTriangle,
  SvgCheckAll,
  SvgEye,
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
} from "@/lib/connectors/ccPair/hooks";
import ActivityCard from "@/views/admin/connectors/ConnectorDetailPage/ActivityCard";
import {
  RUNS_POLL_MS,
  SEARCH_DELAY_MS,
  SEARCH_MAX_LENGTH,
} from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";

const LOADER_ROWS = 2;

/** Which levels the filter shows. */
type Shown = "all" | ActivityGroup;

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
  onResolveRun: (item: ActivityItem) => void;
}
function GroupList({
  state,
  resolving,
  onResolve,
  onResolveRun,
}: GroupListProps) {
  const t = useTranslations("admin.connector.activity");
  if (state.runs.length === 0) return null;
  return (
    <Section alignItems="stretch" gap={1} height="fit">
      <Divider
        title={
          state.closed
            ? t("groups.resolved", { count: state.total })
            : t(`groups.${state.group}`, { count: state.total })
        }
      />
      {state.runs.map((item) => (
        <ActivityCard
          key={`${item.run.kind}-${item.run.attempt.id}`}
          ccPairId={item.ccPairId}
          run={item.run}
          group={state.group}
          closed={state.closed}
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
  className?: string;
}

/** The scope's failed runs and runs with document errors, newest first, with each level's resolved runs a toggle away, and every other run too for the fleet. */
export default function ActivityPanel({
  scope,
  title,
  onClose,
  className,
}: ActivityPanelProps) {
  const t = useTranslations("admin.connector.activity");
  const tPanel = useTranslations("admin.indexing.activities.panel");
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const [shown, setShown] = useState<Shown>("all");
  // Adds the resolved and superseded runs of the levels shown.
  const [showResolved, setShowResolved] = useState(false);
  const [confirmingResolveAll, setConfirmingResolveAll] = useState(false);
  const { resolving, resolve, resolveRun, resolveMatching } =
    useResolveRunErrors();
  // The fleet panel lists every run. A pair's page has its run list for that.
  const shownOptions: Shown[] =
    scope === "fleet"
      ? ["all", "failures", "errors", "other"]
      : ["all", "failures", "errors"];
  const isShown = (group: ActivityGroup) =>
    shownOptions.includes(group) && (shown === "all" || shown === group);

  // The failures and errors totals head the panel, so both always poll.
  const failures = useActivityItems(
    scope,
    "failures",
    false,
    search,
    true,
    RUNS_POLL_MS
  );
  const closedFailures = useActivityItems(
    scope,
    "failures",
    true,
    search,
    showResolved && isShown("failures"),
    RUNS_POLL_MS
  );
  const errors = useActivityItems(
    scope,
    "errors",
    false,
    search,
    true,
    RUNS_POLL_MS
  );
  const closedErrors = useActivityItems(
    scope,
    "errors",
    true,
    search,
    showResolved && isShown("errors"),
    RUNS_POLL_MS
  );
  const other = useActivityItems(
    scope,
    "other",
    false,
    search,
    isShown("other"),
    RUNS_POLL_MS
  );
  const groups = [failures, closedFailures, errors, closedErrors, other].filter(
    (group) => isShown(group.group) && (showResolved || !group.closed)
  );
  const loading = groups.some((group) => group.isLoading && !group.loaded);
  const failed = groups.some((group) => group.failed);
  const empty = groups.every(
    (group) => group.loaded && group.runs.length === 0
  );
  // Resolves the open runs of the one level shown, as the search narrows them.
  const resolvableLevel =
    shown === "failures" ? failures : shown === "errors" ? errors : null;
  const resolveAllLevel =
    shown === "failures" || shown === "errors" ? shown : null;
  const mayResolveRuns =
    scope === "fleet"
      ? [...failures.runs, ...errors.runs].some((item) => item.canResolveRuns)
      : scope.canResolveRuns;
  const emptyTitle =
    search !== ""
      ? t("empty.filtered")
      : shown === "all"
        ? t("empty.title")
        : t(`empty.${shown}`);

  // Full width once the page stacks its columns. Beside them it pins 1.5rem under the settings header and fits the visible height, so a long list scrolls inside the panel instead of lengthening the page. 6rem is that gap plus the body's 4.5rem bottom padding, so the panel still fits when the page ends.
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
                <ActivityCountTags
                  failures={failures.total}
                  errors={errors.total}
                />
              </Section>
            </Section>
            <Section
              flexDirection="row"
              justifyContent="between"
              gap={1}
              height="fit"
              wrap
            >
              <Dropdown>
                <Dropdown.Trigger asChild>
                  <FilterButton
                    icon={SvgActivity}
                    active={shown !== "all" || showResolved}
                    onClear={() => {
                      setShown("all");
                      setShowResolved(false);
                    }}
                  >
                    {showResolved
                      ? t("filter.withResolved", {
                          level: t(`filter.${shown}`),
                        })
                      : t(`filter.${shown}`)}
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
                  items={[
                    ...shownOptions.map((candidate) => ({
                      kind: "option" as const,
                      value: candidate,
                      title: t(`filter.${candidate}`),
                    })),
                    {
                      kind: "toggle" as const,
                      id: "show-resolved",
                      icon: SvgEye,
                      title: t("filter.showResolved"),
                      checked: showResolved,
                      onCheckedChange: setShowResolved,
                    },
                  ]}
                />
              </Dropdown>
              {mayResolveRuns && (
                <Button
                  icon={SvgCheckAll}
                  prominence="tertiary"
                  disabled={
                    resolving ||
                    resolvableLevel === null ||
                    resolvableLevel.runs.length === 0
                  }
                  onClick={() => setConfirmingResolveAll(true)}
                >
                  {t("resolveAll.button")}
                </Button>
              )}
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
                <IllustrationContent title={emptyTitle} />
              ) : (
                groups.map((group) => (
                  <GroupList
                    key={`${group.group}-${group.closed}`}
                    state={group}
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
      {confirmingResolveAll &&
        resolvableLevel !== null &&
        resolveAllLevel !== null && (
          <ConfirmationModalLayout
            icon={SvgCheckAll}
            title={t("resolveAll.title")}
            onClose={() => setConfirmingResolveAll(false)}
            submit={
              <Button
                onClick={() => {
                  setConfirmingResolveAll(false);
                  void resolveMatching(scope, resolveAllLevel, search);
                }}
              >
                {t("resolveAll.confirm")}
              </Button>
            }
          >
            {scope === "fleet"
              ? t("resolveAll.fleetDescription", {
                  count: resolvableLevel.total,
                })
              : t("resolveAll.description", { count: resolvableLevel.total })}
          </ConfirmationModalLayout>
        )}
    </Section>
  );
}
