"use client";

import { useRef } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Badge,
  BadgeButton,
  Button,
  Card,
  Text,
  Tooltip,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgDocFile,
  SvgFileMinus,
  SvgFilePlus,
  SvgFileRefresh,
  SvgFiles,
  SvgListCheck,
  SvgRefreshCw,
  SvgScissors,
  SvgSlowMotion,
  SvgStackLine,
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
import type {
  CapabilityCheckResult,
  CapabilityCheckStatus,
} from "@/lib/connectors/checks/types";
import { applicableResults } from "@/lib/connectors/checks/results";
import type { IndexAttemptSnapshot } from "@/lib/types";
import { getDocsProcessedPerMinute } from "@/lib/indexAttempt";
import { formatDateTimeLog } from "@/lib/dateUtils";
import {
  ERROR_COUNT_TAG,
  isRetryRun,
  runKindLabelKey,
  runStatusTag,
} from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import { CheckRunCard } from "@/views/admin/connectors/ConnectorDetailPage/CheckRunPopover";
import { StageDetailsCard } from "@/views/admin/connectors/ConnectorDetailPage/StageDetailsPopover";
import { RunDetailsHint } from "@/views/admin/connectors/ConnectorDetailPage/InlineDetails";
import { focusDimClass } from "@/views/admin/connectors/ConnectorDetailPage/focusMode";
import RunProgress from "@/views/admin/connectors/ConnectorDetailPage/RunProgress";
import { formatRunLength } from "@/views/admin/connectors/ConnectorDetailPage/runLength";
import LineLayout, {
  LineIconLabel,
  LineTags,
} from "@/views/admin/connectors/shared/LineLayout";

export const RUN_KIND_ICONS = {
  indexing: SvgFiles,
  doc_permission_sync: SvgUserShield,
  group_sync: SvgUsers,
  pruning: SvgScissors,
  checks: SvgListCheck,
} satisfies Record<CCPairRunKind, IconFunctionComponent>;

/** A run's kind glyph. A retry reads apart from the pair's regular indexing. */
export function runKindIcon(run: CCPairRun): IconFunctionComponent {
  return isRetryRun(run) ? SvgRefreshCw : RUN_KIND_ICONS[run.kind];
}

/** A run line's glyph: a retry keeps its own, and any other run shows the slow-motion glyph while it runs. */
function runIcon(run: CCPairRun): IconFunctionComponent {
  if (isActive(run) && !isRetryRun(run)) return SvgSlowMotion;
  return runKindIcon(run);
}

/** The run's results that have a row: checks that apply to the pair. */
export function shownCheckResults(
  run: CheckRunSnapshot
): CapabilityCheckResult[] {
  return applicableResults(run.check_results);
}

/** Whether the line opens stage details or check results under it. */
export function hasInlineDetails(run: CCPairRun): boolean {
  if (run.kind === "indexing") return true;
  return run.kind === "checks" && shownCheckResults(run.attempt).length > 0;
}

/** How many of a check run's shown checks ended in `status`. */
export function checkCount(
  run: CheckRunSnapshot,
  status: CapabilityCheckStatus
): number {
  return shownCheckResults(run).filter((result) => result.status === status)
    .length;
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
    // The run line leaves failed users and groups to the activity card, so a group sync either fails or succeeds.
    case "group_sync":
      return 0;
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
      return run.attempt.total_groups_processed;
    case "pruning":
      return run.attempt.docs_removed;
    case "checks":
      return shownCheckResults(run.attempt).length;
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

/** When the run finished, or `null` while it has not. */
export function finishedAt(run: CCPairRun): string | null {
  if (isActive(run)) return null;
  return run.attempt.time_finished;
}

/** Milliseconds from the run's start to its end, or `null` before either. */
function runDurationMs(run: CCPairRun): number | null {
  const finished = finishedAt(run);
  const started = run.attempt.time_started;
  if (finished === null || started === null) return null;
  return new Date(finished).getTime() - new Date(started).getTime();
}

/** Whole minutes from the run's start to its end, or `null` before either. */
export function runMinutes(run: CCPairRun): number | null {
  const ms = runDurationMs(run);
  return ms === null ? null : Math.max(0, Math.round(ms / 60_000));
}

/** What a run's rate counts: documents indexed or synced, or memberships synced. `null` for a kind with no rate. */
function rateCount(run: CCPairRun): number | null {
  switch (run.kind) {
    case "indexing":
      return run.attempt.total_docs_indexed;
    case "doc_permission_sync":
      return run.attempt.total_docs_synced;
    // Memberships, not groups, measure a group sync's work.
    case "group_sync":
      return run.attempt.total_group_memberships_synced;
    case "pruning":
    case "checks":
      return null;
  }
}

/** What a finished index or sync run moved per minute of its run, or `null` while it goes on or when it moved nothing. */
function finishedRunRate(run: CCPairRun): number | null {
  const count = rateCount(run);
  if (count === null || count === 0) return null;
  const ms = runDurationMs(run);
  if (ms === null || ms <= 0) return null;
  return count / (ms / 60_000);
}

/** What a running permission or group sync moves per minute since it started, or `null` until it has moved something. */
function syncRate(run: CCPairRun, now: number): number | null {
  if (run.kind !== "doc_permission_sync" && run.kind !== "group_sync") {
    return null;
  }
  const started = run.attempt.time_started;
  const count = rateCount(run);
  if (started === null || count === null || count === 0) return null;
  const minutes = (now - new Date(started).getTime()) / 60_000;
  if (minutes <= 0) return null;
  return count / minutes;
}

/** Rates print with two decimals, such as 24.23 docs/min. */
export const RATE_FORMAT = {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
} as const;

/** What an active index or sync run moves per minute so far, or `null` before it has a rate. */
function liveRate(run: CCPairRun, now: number): number | null {
  if (!isActive(run)) return null;
  if (run.kind === "indexing") return getDocsProcessedPerMinute(run.attempt);
  return syncRate(run, now);
}

/** Labels a rate in docs, or memberships for a group sync, per minute, with the run's length once it has ended. */
function useRateLabel(): (
  run: CCPairRun,
  rate: number,
  duration?: string
) => string {
  const t = useTranslations("admin.connector.runs.detail");
  const format = useFormatter();
  return (run, rate, duration) => {
    const shown = format.number(rate, RATE_FORMAT);
    const memberships = run.kind === "group_sync";
    if (duration === undefined) {
      return t(memberships ? "membershipRate" : "rate", { rate: shown });
    }
    return t(memberships ? "membershipRateFinished" : "rateFinished", {
      rate: shown,
      duration,
    });
  };
}

/** Labels an active index or sync run with its live rate, such as "24.23 docs/min", else "Starting sync" until it has one, or `null` for any other run. */
export function useLiveRunDetail(): (run: CCPairRun) => string | null {
  const t = useTranslations("admin.connector.runs.detail");
  const rateLabel = useRateLabel();
  return (run) => {
    const rate = liveRate(run, Date.now());
    if (rate !== null) return rateLabel(run, rate);
    return isActive(run) && rateCount(run) !== null ? t("starting") : null;
  };
}

interface ErrorCountTagProps {
  count: number;
  tooltip: string;
  /** Makes the count a button, named by its tooltip. */
  onClick?: () => void;
}
/** A warning count of errors, or nothing at zero. */
export function ErrorCountTag({ count, tooltip, onClick }: ErrorCountTagProps) {
  const format = useFormatter();
  if (count === 0) return null;
  const tag = {
    ...ERROR_COUNT_TAG,
    title: format.number(count),
    titleColor: "text-04",
  } as const;
  if (onClick !== undefined) {
    return <BadgeButton {...tag} tooltip={tooltip} onClick={onClick} />;
  }
  return <Badge {...tag} tooltip={tooltip} />;
}

interface RunWarningsTagProps {
  run: CCPairRun;
  /** Makes the count a View Errors button. */
  onClick?: () => void;
}
/** The orange count of what the run could not handle, or nothing when it handled everything. */
export function RunWarningsTag({ run, onClick }: RunWarningsTagProps) {
  const t = useTranslations("admin.connector.runs.warnings");
  const tActions = useTranslations("admin.indexing.list.actions");
  const warnings = runWarnings(run);
  return (
    <ErrorCountTag
      count={warnings}
      tooltip={
        onClick === undefined
          ? t(run.kind === "checks" ? "checks" : "tooltip", {
              count: warnings,
            })
          : tActions("viewErrors")
      }
      onClick={onClick}
    />
  );
}

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

interface CountProps {
  icon: IconFunctionComponent;
  value: number;
  tooltip: string;
}
/** A small count with its icon after it, such as new or removed documents. */
function Count({ icon: Icon, value, tooltip }: CountProps) {
  const format = useFormatter();
  // A run line's sub-counts say only what moved.
  if (value === 0) return null;
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

interface DocCountsProps {
  attempt: IndexAttemptSnapshot;
}
/** An index attempt's new, updated and removed documents. */
function DocCounts({ attempt }: DocCountsProps) {
  const t = useTranslations("admin.connector.runs");
  const updated = Math.max(
    0,
    attempt.total_docs_indexed - attempt.new_docs_indexed
  );
  return (
    <CountsRow>
      <Count
        icon={SvgFilePlus}
        value={attempt.new_docs_indexed}
        tooltip={t("counts.newDocs", {
          count: attempt.new_docs_indexed,
        })}
      />
      <Count
        icon={SvgFileRefresh}
        value={updated}
        tooltip={t("counts.updatedDocs", { count: updated })}
      />
      {attempt.docs_removed_from_index > 0 && (
        <Count
          icon={SvgFileMinus}
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
    // The figure already says how many were removed, and the warning pill carries the failures.
    case "pruning":
      return (
        <Figure value={run.attempt.docs_removed} label={t("figures.removed")} />
      );
    case "checks": {
      const attempt = run.attempt;
      const shown: number = shownCheckResults(attempt).length;
      const failed = checkCount(attempt, "failed");
      const incomplete =
        checkCount(attempt, "incomplete") +
        checkCount(attempt, "indeterminate");
      const skipped = checkCount(attempt, "skipped");
      return (
        <>
          <Text font="secondary-body" color="text-03">
            {t("figures.checksRun", { count: shown })}
          </Text>
          {shown > 0 && (
            <CountsRow>
              <Count
                icon={SvgCheckCircle}
                value={checkCount(attempt, "passed")}
                tooltip={t("counts.passedChecks", {
                  count: checkCount(attempt, "passed"),
                })}
              />
              {incomplete > 0 && (
                <Count
                  icon={SvgAlertCircle}
                  value={incomplete}
                  tooltip={t("counts.incompleteChecks", { count: incomplete })}
                />
              )}
              {skipped > 0 && (
                <Count
                  icon={SvgXCircle}
                  value={skipped}
                  tooltip={t("counts.skippedChecks", { count: skipped })}
                />
              )}
              {failed > 0 && (
                <Count
                  icon={SvgXOctagon}
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
          <DocCounts attempt={run.attempt} />
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
              value={attempt.total_users_processed}
              tooltip={t("counts.users", {
                count: attempt.total_users_processed,
              })}
            />
            <Count
              icon={SvgUsers}
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
  /** Whether the line's stage details or check results show under it. The open line is raised. */
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Another line's details are open, so this line steps back. */
  dimmed: boolean;
  /** An activity elsewhere on the page points at this run, so the line rises as an open one does. */
  lifted?: boolean;
}

/** One run in the pair's run list: what ran and when, how it ended, and what it moved, with its stage details or check results inline under it. */
export default function RunRow({
  run,
  canCancel,
  onCancel,
  onViewLogs,
  open,
  onOpenChange,
  dimmed,
  lifted = false,
}: RunRowProps) {
  const t = useTranslations("admin.connector.runs");
  const format = useFormatter();
  const rateLabel = useRateLabel();
  const liveDetail = useLiveRunDetail();
  const hintRef = useRef<HTMLElement>(null);
  const tag = runStatusTag(run);
  const active = isActive(run);
  const failed = run.attempt.status === "failed";
  const hasChecks =
    run.kind === "checks" && shownCheckResults(run.attempt).length > 0;

  const finished = finishedAt(run);
  // The detail no longer carries the finish time, so the tooltip does.
  const finishedTime =
    finished === null ? undefined : formatDateTimeLog(finished);

  // Before it ends: the live rate, Starting sync until a run with a rate has one, else Running.
  // Once it ends: the rate and how long it took, or only how long for a run with no rate or one that moved nothing.
  function detail(): string {
    if (finished === null) return liveDetail(run) ?? t("detail.running");
    const ms = runDurationMs(run);
    if (ms === null) return formatDateTimeLog(finished);
    const duration = formatRunLength(format, ms);
    const rate = finishedRunRate(run);
    if (rate === null) return t("detail.runtime", { duration });
    return rateLabel(run, rate, duration);
  }

  const warnings = runWarnings(run);
  const emphasized = active || failed || warnings > 0;
  const hasLogs = runErrorText(run) !== null;
  // Logs stay a hover action on a clean run and show outright once something went wrong.
  const logsShown = failed || warnings > 0 || hasLogs;

  function toggle() {
    onOpenChange(!open);
  }

  // Focus goes back to the hint, as it did when a popover closed.
  function close() {
    onOpenChange(false);
    hintRef.current?.focus();
  }

  return (
    <Section
      alignItems="stretch"
      gap={1}
      height="fit"
      className={focusDimClass(dimmed)}
    >
      <Card
        padding={1}
        shadow={open || lifted ? "md" : "none"}
        className="group/run-line"
        data-testid="run-row"
      >
        <LineLayout
          variant="run"
          a={
            // Below 640 px the wrapped line sets the time before the type on one line.
            <Section
              alignItems="start"
              gap={1}
              height="fit"
              className="@max-[38.75rem]:flex-row-reverse @max-[38.75rem]:items-center @max-[38.75rem]:justify-end"
            >
              <LineIconLabel
                icon={runIcon(run)}
                label={t(`kinds.${runKindLabelKey(run)}`)}
              />
              <Text
                font={emphasized ? "secondary-action" : "secondary-body"}
                color={emphasized ? "text-04" : "text-03"}
                wordWrap="whitespace-nowrap"
              >
                {formatDateTimeLog(run.time_created)}
              </Text>
            </Section>
          }
          b={
            <>
              <LineTags tag={tag}>
                {run.kind === "indexing" && run.attempt.is_new_model && (
                  <Badge
                    title={t("newModel.label")}
                    color="info"
                    tooltip={t("newModel.tooltip")}
                  />
                )}
                {run.kind === "indexing" && (
                  <RunDetailsHint
                    icon={SvgStackLine}
                    label={t("actions.stages")}
                    open={open}
                    onClick={toggle}
                    ref={hintRef}
                  />
                )}
                {hasChecks && (
                  <RunDetailsHint
                    icon={SvgListCheck}
                    label={t("actions.checks")}
                    open={open}
                    onClick={toggle}
                    ref={hintRef}
                  />
                )}
                <RunWarningsTag run={run} />
              </LineTags>
              <Tooltip tooltip={finishedTime} side="top">
                <Text font="secondary-body" color="text-03">
                  {detail()}
                </Text>
              </Tooltip>
            </>
          }
          c={<RunFigures run={run} />}
          d={
            <>
              {canCancel && run.kind === "indexing" && active && (
                <Button
                  icon={SvgXCircle}
                  prominence="internal"
                  size="sm"
                  tooltip={t("actions.cancel")}
                  aria-label={t("actions.cancel")}
                  onClick={onCancel}
                />
              )}
              <div
                className={cn(
                  !logsShown &&
                    "opacity-0 transition-opacity focus-within:opacity-100 group-hover/run-line:opacity-100 no-hover:opacity-100"
                )}
              >
                {/* Every line has the action, and a run that recorded no trace or message has nothing to open. */}
                <Button
                  icon={SvgDocFile}
                  prominence="internal"
                  size="sm"
                  tooltip={t(hasLogs ? "actions.logs" : "actions.noLogs")}
                  aria-label={t("actions.logs")}
                  disabled={!hasLogs}
                  onClick={onViewLogs}
                />
              </div>
            </>
          }
        />
        {run.kind === "indexing" && active && run.attempt.progress && (
          <RunProgress progress={run.attempt.progress} />
        )}
      </Card>
      {open && run.kind === "indexing" && (
        <StageDetailsCard
          indexAttemptId={run.attempt.id}
          noDocs={!active && run.attempt.total_docs_indexed === 0}
          onClose={close}
        />
      )}
      {open && run.kind === "checks" && hasChecks && (
        <CheckRunCard run={run.attempt} onClose={close} />
      )}
    </Section>
  );
}
