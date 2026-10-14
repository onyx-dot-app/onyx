"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Button, Card, Popover, Tag, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import {
  SvgAlertTriangle,
  SvgFileText,
  SvgMinusCircle,
  SvgPlusCircle,
  SvgRefreshCw,
  SvgTextLines,
  SvgUserCheck,
  SvgUsers,
  SvgXCircle,
} from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import type { CCPairRun, CCPairRunKind } from "@/lib/connectors/types";
import { getDocsProcessedPerMinute } from "@/lib/indexAttempt";
import { attemptStatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import StageDetailsPopoverContent, {
  StageDetailsTrigger,
} from "@/views/admin/connectors/ConnectorDetailPage/StageDetailsPopover";

export const RUN_KIND_ICONS = {
  indexing: SvgFileText,
  doc_permission_sync: SvgUserCheck,
  group_sync: SvgUsers,
} satisfies Record<CCPairRunKind, IconFunctionComponent>;

/** A run's error text: its trace, else its error message, or `null` when it has neither. */
export function runErrorText(run: CCPairRun): string | null {
  if (run.attempt.full_exception_trace !== null) {
    return run.attempt.full_exception_trace;
  }
  return run.kind === "indexing"
    ? run.attempt.error_msg
    : run.attempt.error_message;
}

/** The documents a run could not handle: indexing errors, or docs a sync could not read. */
function runWarnings(run: CCPairRun): number {
  switch (run.kind) {
    case "indexing":
      return run.attempt.error_count;
    case "doc_permission_sync":
      return run.attempt.docs_with_permission_errors;
    case "group_sync":
      return 0;
  }
}

function isActive(run: CCPairRun): boolean {
  return (
    run.attempt.status === "in_progress" || run.attempt.status === "not_started"
  );
}

/** When the run finished, or `null` while it has not. */
function finishedAt(run: CCPairRun): string | null {
  if (isActive(run)) return null;
  return run.attempt.time_finished;
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
/** A small count with its icon, such as new or removed documents. */
function Count({ icon, value, tooltip }: CountProps) {
  const format = useFormatter();
  return (
    <Tag
      icon={icon}
      title={format.number(value)}
      tooltip={tooltip}
      color="gray"
    />
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

interface RunFiguresProps {
  run: CCPairRun;
}
/** What the run moved: documents for indexing and doc syncs, memberships for group syncs. */
function RunFigures({ run }: RunFiguresProps) {
  const t = useTranslations("admin.connector.runs");
  switch (run.kind) {
    case "indexing": {
      const attempt = run.attempt;
      return (
        <>
          <Figure
            value={attempt.total_docs_indexed}
            label={t("figures.indexed")}
          />
          <CountsRow>
            <Count
              icon={SvgPlusCircle}
              value={attempt.new_docs_indexed}
              tooltip={t("counts.newDocs", {
                count: attempt.new_docs_indexed,
              })}
            />
            <Count
              icon={SvgRefreshCw}
              value={Math.max(
                0,
                attempt.total_docs_indexed - attempt.new_docs_indexed
              )}
              tooltip={t("counts.updatedDocs")}
            />
            {attempt.docs_removed_from_index > 0 && (
              <Count
                icon={SvgMinusCircle}
                value={attempt.docs_removed_from_index}
                tooltip={t("counts.removedDocs", {
                  count: attempt.docs_removed_from_index,
                })}
              />
            )}
          </CountsRow>
        </>
      );
    }
    case "doc_permission_sync":
      return (
        <Figure
          value={run.attempt.total_docs_synced}
          label={t("figures.synced")}
        />
      );
    case "group_sync": {
      const attempt = run.attempt;
      return (
        <>
          <Figure
            value={attempt.total_group_memberships_synced}
            label={t("figures.memberships")}
          />
          <CountsRow>
            <Count
              icon={SvgUserCheck}
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
}

/** One run in the pair's run list: what ran and when, how it ended, and what it moved. */
export default function RunRow({
  run,
  canCancel,
  onCancel,
  onViewLogs,
}: RunRowProps) {
  const t = useTranslations("admin.connector.runs");
  const tBadges = useTranslations("admin.status.badges");
  const format = useFormatter();
  const tag = attemptStatusTag(run.attempt.status, run.kind !== "indexing");
  const active = isActive(run);
  const failed = run.attempt.status === "failed";
  const stamp = (value: string) =>
    format.dateTime(new Date(value), {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });

  // Queued, then the live rate, then when it finished and how long it took.
  function detail(): string {
    if (run.attempt.status === "not_started") return t("detail.queued");
    if (run.kind === "indexing" && active) {
      const rate = getDocsProcessedPerMinute(run.attempt);
      if (rate !== null) {
        return t("detail.rate", {
          rate: format.number(rate, { maximumFractionDigits: 2 }),
        });
      }
    }
    const finished = finishedAt(run);
    if (finished === null) return t("detail.running");
    const started = run.attempt.time_started;
    if (started === null) return stamp(finished);
    const minutes = Math.max(
      0,
      Math.round(
        (new Date(finished).getTime() - new Date(started).getTime()) / 60_000
      )
    );
    return t("detail.finished", { time: stamp(finished), minutes });
  }

  const warnings = runWarnings(run);
  const hasLogs = runErrorText(run) !== null;

  // The stage details popover spans the row, so the row is its anchor.
  return (
    <Popover>
      <Popover.Anchor asChild>
        <Card color="background-tint-00" border="none" rounding={2} padding={1}>
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
                icon={RUN_KIND_ICONS[run.kind]}
                title={t(`kinds.${run.kind}`)}
                sizePreset="secondary"
                variant="body"
                color="muted"
                width="fit"
              />
              <Text
                font={active || failed ? "secondary-action" : "secondary-body"}
                color={active || failed ? "text-04" : "text-03"}
              >
                {stamp(run.time_created)}
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
                />
                {run.kind === "indexing" && <StageDetailsTrigger />}
                {warnings > 0 && (
                  <Tag
                    icon={SvgAlertTriangle}
                    title={format.number(warnings)}
                    tooltip={t("warnings.tooltip", { count: warnings })}
                    color="amber"
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
                  icon={SvgTextLines}
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
    </Popover>
  );
}
