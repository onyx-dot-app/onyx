"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Button, Card, Popover, Tag, Text, Tooltip } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { formatTimestamp } from "@opal/time";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgFileMinus,
  SvgFilePlus,
  SvgFileRefresh,
  SvgFiles,
  SvgListCheck,
  SvgScissors,
  SvgSlowMotion,
  SvgUser,
  SvgUserShield,
  SvgUsers,
  SvgXCircle,
  SvgXOctagon,
} from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import type {
  CCPairRun,
  CCPairRunKind,
  CheckRunSnapshot,
} from "@/lib/connectors/types";
import type { IndexAttemptSnapshot } from "@/lib/types";
import { getDocsProcessedPerMinute } from "@/lib/indexAttempt";
import { runStatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import CheckRunPopoverContent, {
  CheckRunTrigger,
} from "@/views/admin/connectors/ConnectorDetailPage/CheckRunPopover";
import StageDetailsPopoverContent, {
  StageDetailsTrigger,
} from "@/views/admin/connectors/ConnectorDetailPage/StageDetailsPopover";
import { focusDimClass } from "@/views/admin/connectors/ConnectorDetailPage/focusMode";

export const RUN_KIND_ICONS = {
  indexing: SvgFiles,
  doc_permission_sync: SvgUserShield,
  group_sync: SvgUsers,
  pruning: SvgScissors,
  checks: SvgListCheck,
} satisfies Record<CCPairRunKind, IconFunctionComponent>;

/** How many of a check run's checks ended in `status`. */
export function checkCount(
  run: CheckRunSnapshot,
  status: CheckRunSnapshot["check_results"][number]["status"]
): number {
  return run.check_results.filter((result) => result.status === status).length;
}

/** The run's own error message, without its trace. */
export function runErrorMessage(run: CCPairRun): string | null {
  return run.kind === "indexing"
    ? run.attempt.error_msg
    : run.attempt.error_message;
}

/** The run's stack trace. Prunes and check runs keep none. */
export function runTrace(run: CCPairRun): string | null {
  switch (run.kind) {
    case "indexing":
    case "doc_permission_sync":
    case "group_sync":
      return run.attempt.full_exception_trace;
    case "pruning":
    case "checks":
      return null;
  }
}

/** A run's error text: its trace, else its error message, or `null` when it has neither. */
export function runErrorText(run: CCPairRun): string | null {
  return runTrace(run) ?? runErrorMessage(run);
}

/** What a run could not handle: indexing errors, docs a sync could not read, or checks that failed. */
export function runWarnings(run: CCPairRun): number {
  switch (run.kind) {
    case "indexing":
      return run.attempt.error_count;
    case "doc_permission_sync":
      return run.attempt.docs_with_permission_errors;
    case "group_sync":
      return run.attempt.total_groups_failed;
    case "pruning":
      return run.attempt.docs_failed;
    case "checks":
      return checkCount(run.attempt, "failed");
  }
}

/** What the run moved: documents indexed, synced or removed, memberships, or checks run. */
export function runMoved(run: CCPairRun): number {
  switch (run.kind) {
    case "indexing":
      return run.attempt.total_docs_indexed;
    case "doc_permission_sync":
      return run.attempt.total_docs_synced;
    case "group_sync":
      return run.attempt.total_group_memberships_synced;
    case "pruning":
      return run.attempt.docs_removed;
    case "checks":
      return run.attempt.check_results.length;
  }
}

export function isActive(run: CCPairRun): boolean {
  switch (run.kind) {
    case "indexing":
    case "doc_permission_sync":
    case "group_sync":
      return (
        run.attempt.status === "in_progress" ||
        run.attempt.status === "not_started"
      );
    case "pruning":
      return run.attempt.status === "in_progress";
    case "checks":
      return run.attempt.status === "running";
  }
}

/** Whether the run ended in failure, as the feed's failed status group counts it. */
export function isFailed(run: CCPairRun): boolean {
  return (
    run.attempt.status === "failed" || run.attempt.status === "failed_to_run"
  );
}

/** When the run finished, or `null` while it has not. */
export function finishedAt(run: CCPairRun): string | null {
  if (isActive(run)) return null;
  return run.attempt.time_finished;
}

/** Whole minutes from the run's start to its end, or `null` before either. */
export function runMinutes(run: CCPairRun): number | null {
  const finished = finishedAt(run);
  const started = run.attempt.time_started;
  if (finished === null || started === null) return null;
  return Math.max(
    0,
    Math.round(
      (new Date(finished).getTime() - new Date(started).getTime()) / 60_000
    )
  );
}

/** What a running permission or group sync moves per minute since it started, or `null` before it starts. */
export function syncRate(run: CCPairRun, now: number): number | null {
  if (run.kind !== "doc_permission_sync" && run.kind !== "group_sync") {
    return null;
  }
  const started = run.attempt.time_started;
  if (started === null) return null;
  const minutes = (now - new Date(started).getTime()) / 60_000;
  if (minutes <= 0) return null;
  return runMoved(run) / minutes;
}

/** Rates print with two decimals, such as 24.23 docs/min. */
const RATE_FORMAT = {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
} as const;

interface FigureProps {
  value: number;
  label: string | RichStr;
}
function Figure({ value, label }: FigureProps) {
  const format = useFormatter();
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="end"
      gap={1}
      width="fit"
      height="fit"
    >
      <Text font="main-ui-action" color="text-04">
        {format.number(value)}
      </Text>
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
    </Section>
  );
}

/** How a count shows: a gray tag, or a plain number with its icon after it as run rows show it. */
export type CountLook = "tag" | "plain";

interface CountProps {
  icon: IconFunctionComponent;
  value: number;
  tooltip: string;
  look: CountLook;
}
/** A small count with its icon, such as new or removed documents. */
function Count({ icon: Icon, value, tooltip, look }: CountProps) {
  const format = useFormatter();
  if (look === "tag") {
    return (
      <Tag
        icon={Icon}
        title={format.number(value)}
        tooltip={tooltip}
        color="gray"
      />
    );
  }
  return (
    <Tooltip tooltip={tooltip} side="top">
      <Section
        flexDirection="row"
        alignItems="center"
        gap={0.25}
        width="fit"
        height="fit"
      >
        <Text font="secondary-body" color="text-03">
          {format.number(value)}
        </Text>
        <Icon size={12} className="shrink-0 stroke-text-02" />
      </Section>
    </Tooltip>
  );
}

interface CountsRowProps {
  children: React.ReactNode;
}
function CountsRow({ children }: CountsRowProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      gap={1}
      width="fit"
      height="fit"
    >
      {children}
    </Section>
  );
}

export interface DocCountsProps {
  attempt: IndexAttemptSnapshot;
  /** @default "tag" */
  look?: CountLook;
}
/** An index attempt's new, updated and removed documents. */
export function DocCounts({ attempt, look = "tag" }: DocCountsProps) {
  const t = useTranslations("admin.connector.runs");
  return (
    <CountsRow>
      <Count
        icon={SvgFilePlus}
        look={look}
        value={attempt.new_docs_indexed}
        tooltip={t("counts.newDocs", {
          count: attempt.new_docs_indexed,
        })}
      />
      <Count
        icon={SvgFileRefresh}
        look={look}
        value={Math.max(
          0,
          attempt.total_docs_indexed - attempt.new_docs_indexed
        )}
        tooltip={t("counts.updatedDocs")}
      />
      {attempt.docs_removed_from_index > 0 && (
        <Count
          icon={SvgFileMinus}
          look={look}
          value={attempt.docs_removed_from_index}
          tooltip={t("counts.removedDocs", {
            count: attempt.docs_removed_from_index,
          })}
        />
      )}
    </CountsRow>
  );
}

interface RunFiguresProps {
  run: CCPairRun;
}
/** What the run moved, with its breakdown: new and updated documents, users and groups, or checks by outcome. */
function RunFigures({ run }: RunFiguresProps) {
  const t = useTranslations("admin.connector.runs");
  switch (run.kind) {
    case "pruning":
      return (
        <>
          <Figure
            value={run.attempt.docs_removed}
            label={t("figures.removed")}
          />
          <CountsRow>
            <Count
              icon={SvgFileMinus}
              look="plain"
              value={run.attempt.docs_removed}
              tooltip={t("counts.removedDocs", {
                count: run.attempt.docs_removed,
              })}
            />
          </CountsRow>
        </>
      );
    case "checks": {
      const attempt = run.attempt;
      const failed = checkCount(attempt, "failed");
      const skipped = checkCount(attempt, "skipped");
      return (
        <>
          <Text font="secondary-body" color="text-03">
            {t("figures.checksRun", { count: attempt.check_results.length })}
          </Text>
          {attempt.check_results.length > 0 && (
            <CountsRow>
              <Count
                icon={SvgCheckCircle}
                look="plain"
                value={checkCount(attempt, "passed")}
                tooltip={t("counts.passedChecks", {
                  count: checkCount(attempt, "passed"),
                })}
              />
              {skipped > 0 && (
                <Count
                  icon={SvgXCircle}
                  look="plain"
                  value={skipped}
                  tooltip={t("counts.skippedChecks", { count: skipped })}
                />
              )}
              {failed > 0 && (
                <Count
                  icon={SvgXOctagon}
                  look="plain"
                  value={failed}
                  tooltip={t("counts.failedChecks", { count: failed })}
                />
              )}
            </CountsRow>
          )}
        </>
      );
    }
    case "indexing":
      return (
        <>
          <Figure
            value={run.attempt.total_docs_indexed}
            label={t("figures.indexed")}
          />
          <DocCounts attempt={run.attempt} look="plain" />
        </>
      );
    case "doc_permission_sync":
      return (
        <>
          <Figure
            value={run.attempt.total_docs_synced}
            label={t("figures.synced")}
          />
          <CountsRow>
            <Count
              icon={SvgFileRefresh}
              look="plain"
              value={run.attempt.total_docs_synced}
              tooltip={t("counts.syncedDocs", {
                count: run.attempt.total_docs_synced,
              })}
            />
          </CountsRow>
        </>
      );
    case "group_sync": {
      const attempt = run.attempt;
      return (
        <>
          <Figure
            value={attempt.total_group_memberships_synced}
            label={t("figures.synced")}
          />
          <CountsRow>
            <Count
              icon={SvgUser}
              look="plain"
              value={attempt.total_users_processed}
              tooltip={t("counts.users", {
                count: attempt.total_users_processed,
              })}
            />
            <Count
              icon={SvgUsers}
              look="plain"
              value={attempt.total_groups_processed}
              tooltip={t("counts.groups", {
                count: attempt.total_groups_processed,
              })}
            />
          </CountsRow>
        </>
      );
    }
  }
}

export interface RunRowProps {
  run: CCPairRun;
  /** Whether the caller may cancel. The action shows only on an active index attempt. */
  canCancel: boolean;
  onCancel: () => void;
  onViewLogs: () => void;
  /** Whether the row's stage or checks popover is open. The open row is raised. */
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Another row's popover is open, so this row steps back. */
  dimmed: boolean;
}

/** One run in the pair's run list: what ran and when, how it ended, and what it moved. */
export default function RunRow({
  run,
  canCancel,
  onCancel,
  onViewLogs,
  open,
  onOpenChange,
  dimmed,
}: RunRowProps) {
  const t = useTranslations("admin.connector.runs");
  const tBadges = useTranslations("admin.status.badges");
  const format = useFormatter();
  const tag = runStatusTag(run);
  const active = isActive(run);
  const failed = run.attempt.status === "failed";
  const canceled = run.attempt.status === "canceled";

  // Queued, then the live rate, then when it finished and how long it took.
  function detail(): string {
    if (run.attempt.status === "not_started") return t("detail.queued");
    if (run.kind === "indexing" && active) {
      const rate = getDocsProcessedPerMinute(run.attempt);
      if (rate !== null) {
        return t("detail.rate", { rate: format.number(rate, RATE_FORMAT) });
      }
    }
    if (active) {
      const rate = syncRate(run, Date.now());
      if (rate !== null) {
        return t(
          run.kind === "group_sync" ? "detail.membershipRate" : "detail.rate",
          { rate: format.number(rate, RATE_FORMAT) }
        );
      }
    }
    const finished = finishedAt(run);
    if (finished === null) return t("detail.running");
    const minutes = runMinutes(run);
    if (minutes === null) return formatTimestamp(finished);
    return t("detail.finished", { time: formatTimestamp(finished), minutes });
  }

  const warnings = runWarnings(run);
  const emphasized = active || failed || warnings > 0;
  const hasLogs = runErrorText(run) !== null;

  // The stage details popover spans the row, so the row is its anchor.
  return (
    <Section
      alignItems="stretch"
      height="fit"
      className={focusDimClass(dimmed)}
    >
      <Popover open={open} onOpenChange={onOpenChange}>
        <Popover.Anchor asChild>
          <Card
            color="background-tint-00"
            border="none"
            rounding={2}
            padding={1}
            shadow={open ? "md" : "none"}
          >
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={1}
              height="fit"
            >
              <Section
                alignItems="start"
                gap={1}
                padding={1}
                height="fit"
                className="min-w-0 flex-1"
              >
                <Content
                  icon={
                    active || canceled
                      ? SvgSlowMotion
                      : RUN_KIND_ICONS[run.kind]
                  }
                  title={t(`kinds.${run.kind}`)}
                  sizePreset="secondary"
                  variant="body"
                  color="muted"
                  width="fit"
                />
                <Text
                  font={emphasized ? "secondary-action" : "secondary-body"}
                  color={emphasized ? "text-04" : "text-03"}
                >
                  {formatTimestamp(run.time_created)}
                </Text>
              </Section>

              <Section
                alignItems="start"
                gap={1}
                padding={1}
                width={12}
                height="fit"
                className="shrink-0"
              >
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  gap={1}
                  width="fit"
                  height="fit"
                >
                  <Tag
                    icon={tag.icon}
                    title={tBadges(tag.labelKey)}
                    color={tag.color}
                    variant="status"
                    font="secondary-body"
                  />
                  {run.kind === "indexing" && run.attempt.is_new_model && (
                    <Tag
                      title={t("newModel.label")}
                      tooltip={t("newModel.tooltip")}
                      color="purple"
                    />
                  )}
                  {run.kind === "indexing" && (
                    <StageDetailsTrigger open={open} />
                  )}
                  {run.kind === "checks" &&
                    run.attempt.check_results.length > 0 && (
                      <CheckRunTrigger open={open} />
                    )}
                  {warnings > 0 && (
                    <Tag
                      icon={SvgAlertTriangle}
                      title={format.number(warnings)}
                      tooltip={t(
                        run.kind === "checks"
                          ? "warnings.checks"
                          : "warnings.tooltip",
                        { count: warnings }
                      )}
                      color="orange"
                      variant="count"
                      font="secondary-body"
                    />
                  )}
                </Section>
                <Text font="secondary-body" color="text-03">
                  {detail()}
                </Text>
              </Section>

              <Section
                alignItems="end"
                gap={1}
                padding={1}
                width={9}
                height="fit"
                className="shrink-0"
              >
                <RunFigures run={run} />
              </Section>

              <Section
                flexDirection="row"
                justifyContent="end"
                gap={1}
                width={3.5}
                height="fit"
                className="shrink-0"
              >
                {canCancel && run.kind === "indexing" && active && (
                  <Button
                    icon={SvgXCircle}
                    prominence="tertiary"
                    size="sm"
                    tooltip={t("actions.cancel")}
                    aria-label={t("actions.cancel")}
                    onClick={onCancel}
                  />
                )}
                {hasLogs && (
                  <Button
                    icon={SvgAlertTriangle}
                    prominence="tertiary"
                    size="sm"
                    tooltip={t("actions.logs")}
                    aria-label={t("actions.logs")}
                    onClick={onViewLogs}
                  />
                )}
              </Section>
            </Section>
          </Card>
        </Popover.Anchor>
        {run.kind === "indexing" && (
          <StageDetailsPopoverContent indexAttemptId={run.attempt.id} />
        )}
        {run.kind === "checks" && run.attempt.check_results.length > 0 && (
          <CheckRunPopoverContent run={run.attempt} />
        )}
      </Popover>
    </Section>
  );
}
