"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  Popover,
  SelectButton,
  Tag,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import {
  SvgAlertTriangle,
  SvgCheckAll,
  SvgCheckCircle,
  SvgCheckSquare,
  SvgFiles,
  SvgTextLines,
  SvgUserShield,
  SvgUsers,
  SvgXOctagon,
} from "@opal/icons";
import type { CardColor, IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";
import type {
  CCPairRef,
  CCPairRun,
  CCPairRunKind,
} from "@/lib/connectors/types";
import type { ActivityGroup } from "@/lib/connectors/ccPair/hooks";
import { getSourceMetadata } from "@/lib/connectors/utils";
import { formatDateTimeLog } from "@/lib/dateUtils";
import CheckRunPopoverContent from "@/views/admin/connectors/ConnectorDetailPage/CheckRunPopover";
import FailedDocsPopoverContent from "@/views/admin/connectors/ConnectorDetailPage/FailedDocsPopover";
import StackTracePopoverContent from "@/views/admin/connectors/ConnectorDetailPage/StackTracePopover";
import {
  RUN_KIND_ICONS,
  isActive,
  runErrorMessage,
  runMinutes,
  runMoved,
  runTrace,
  runWarnings,
} from "@/views/admin/connectors/ConnectorDetailPage/RunRow";

// A Tag is clickable only with an onClick, and the popover trigger around it handles the click.
const NOOP = () => {};

const GROUP_STYLE: Record<
  ActivityGroup,
  {
    color: CardColor;
    icon: IconFunctionComponent;
    stroke: string;
    closedStroke: string;
    /** The 1px edge a hovered or selected card takes, in the level's 02 color. */
    outline: string;
  }
> = {
  failures: {
    color: "status-error-00",
    icon: SvgXOctagon,
    stroke: "stroke-status-error-05",
    closedStroke: "stroke-status-error-02",
    outline: "outline-status-error-02",
  },
  errors: {
    color: "status-warning-00",
    icon: SvgAlertTriangle,
    stroke: "stroke-status-warning-05",
    closedStroke: "stroke-status-warning-02",
    outline: "outline-status-warning-02",
  },
  other: {
    color: "background-tint-00",
    icon: SvgCheckCircle,
    stroke: "stroke-status-success-05",
    closedStroke: "stroke-status-success-02",
    outline: "outline-border-01",
  },
};

/** What each kind's failed items are: documents, users, groups or checks. */
const WARNING_ICONS = {
  indexing: SvgFiles,
  doc_permission_sync: SvgUserShield,
  group_sync: SvgUsers,
  pruning: SvgFiles,
  checks: SvgXOctagon,
} satisfies Record<CCPairRunKind, IconFunctionComponent>;

type CardState =
  | "failed"
  | "running"
  | "stopped"
  | "errors"
  | "resolved"
  | "inProgress"
  | "canceled"
  | "succeeded";

/** The title's state key: how the run stands in its group. A closed card reads as it did when open, except a run whose document errors were all resolved, which says so. */
function cardState(
  run: CCPairRun,
  group: ActivityGroup,
  closed: boolean
): CardState {
  const stopped =
    run.attempt.status === "canceled" || run.attempt.status === "interrupted";
  switch (group) {
    case "failures":
      return "failed";
    case "errors":
      if (closed && run.resolved_at === null) return "resolved";
      if (isActive(run)) return "running";
      return stopped ? "stopped" : "errors";
    case "other":
      if (isActive(run)) return "inProgress";
      return stopped ? "canceled" : "succeeded";
  }
}

interface FailureReason {
  /** The error's first sentence, without its end mark. */
  reason: string;
  /** What follows the first sentence; `null` when nothing does. */
  rest: string | null;
}

/** Splits an error into its first sentence and the rest. */
function splitReason(message: string): FailureReason {
  const trimmed = message.trim();
  const first = /^[\s\S]+?[.!?](?=\s|$)/.exec(trimmed)?.[0] ?? trimmed;
  const rest = trimmed.slice(first.length).trim();
  return {
    reason: first.replace(/[.!?]+$/, ""),
    rest: rest === "" ? null : rest,
  };
}

export interface ActivityCardProps {
  ccPairId: number;
  run: CCPairRun;
  group: ActivityGroup;
  /** The run is resolved or superseded: it keeps its level's icon, with every element faded. */
  closed: boolean;
  /** Names the pair in place of the run's kind, for a feed across pairs. */
  connector?: CCPairRef;
  /** Whether the viewer may re-fetch single documents of this pair. Hides the resolve actions otherwise. */
  canResolve: boolean;
  /** Whether the viewer may mark the run resolved. */
  canResolveRuns: boolean;
  /** Resolves these errors of the run by a targeted reindex, or every open one when `null`. */
  onResolve: (errorIds: number[] | null) => void;
  /** Marks the run resolved without a reindex. */
  onResolveRun: () => void;
  /** A resolve is in flight, so the resolve actions wait for it. */
  resolving: boolean;
}

/** One run in an activity list: when, which kind, how it stands in its group, its trace and failed documents. */
export default function ActivityCard({
  ccPairId,
  run,
  group,
  closed,
  connector,
  canResolve,
  canResolveRuns,
  onResolve,
  onResolveRun,
  resolving,
}: ActivityCardProps) {
  const t = useTranslations("admin.connector.activity");
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [openPopover, setOpenPopover] = useState<"trace" | "items" | null>(
    null
  );
  const selected = openPopover !== null;
  const togglePopover = (popover: "trace" | "items") => (open: boolean) =>
    setOpenPopover((current) =>
      open ? popover : current === popover ? null : current
    );
  const tRuns = useTranslations("admin.connector.runs");
  const active = isActive(run);
  const style = GROUP_STYLE[group];
  const StatusIcon = active ? IconLoader : style.icon;
  const IdentityIcon =
    connector === undefined
      ? RUN_KIND_ICONS[run.kind]
      : getSourceMetadata(connector.source).icon;
  const identity =
    connector === undefined ? tRuns(`kinds.${run.kind}`) : connector.name;
  const minutes = runMinutes(run);
  const warnings = runWarnings(run);
  const trace = runTrace(run);
  // The list holds open document errors, so only an index attempt with some lists its documents.
  const openDocs =
    run.kind === "indexing" ? run.attempt.open_doc_error_count : 0;
  const listsDocs = openDocs > 0;
  const resolvable = canResolve && listsDocs;
  // A failed check run lists what failed instead of a stack trace.
  const listsChecks = run.kind === "checks" && warnings > 0;
  const state = cardState(run, group, closed);
  // A run still going can fail again, so it is resolved once it ends.
  const resolvesRun = canResolveRuns && !closed && !active && group !== "other";
  const mutedColor = closed ? "text-02" : "text-03";

  // A failure, superseded or not, titles with the error's first sentence and describes with the rest. A run with errors reports what it still did.
  let description: string | null = null;
  let title = t(`title.${run.kind}.${state}`);
  if (group === "failures") {
    const message = runErrorMessage(run);
    const split = message ? splitReason(message) : null;
    if (split !== null && split.reason !== "") {
      title = t(`title.${run.kind}.failedWith`, { reason: split.reason });
      description = split.rest;
    } else {
      description = listsChecks
        ? t("description.checksFailed", { count: warnings })
        : null;
    }
  } else if (minutes !== null) {
    description = t(`description.${run.kind}`, {
      count: runMoved(run),
      minutes,
    });
  }
  // A closed card keeps the pill it had when open, only faded.
  const docsLabel = t(`tags.${run.kind}`, {
    count: listsDocs ? openDocs : warnings,
  });

  const pillIconColor = closed ? undefined : "orange";

  // The outline draws the edge inside the card, so hovering does not shift the list.
  return (
    <Section
      alignItems="stretch"
      height="fit"
      className={cn(
        "rounded-08 -outline-offset-1",
        (hovered || selected) && `outline-1 outline-solid ${style.outline}`
      )}
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setFocused(false);
        }
      }}
    >
      <Card
        color={
          hovered && !selected
            ? "background-tint-02"
            : closed
              ? "background-tint-01"
              : style.color
        }
        border="none"
        rounding={2}
        padding={1}
        shadow={selected ? "md" : "none"}
      >
        <Section alignItems="stretch" gap={0} height="fit">
          <Section
            flexDirection="row"
            alignItems="start"
            gap={1}
            padding={1}
            height="fit"
          >
            <Section
              alignItems="center"
              justifyContent="center"
              padding={0.5}
              width="fit"
              height="fit"
            >
              <StatusIcon
                size={16}
                className={
                  active
                    ? "stroke-status-info-05"
                    : closed
                      ? style.closedStroke
                      : style.stroke
                }
              />
            </Section>
            <Section
              alignItems="stretch"
              gap={0}
              height="fit"
              className="min-w-0 flex-1"
            >
              <Section
                flexDirection="row"
                justifyContent="between"
                alignItems="center"
                gap={1}
                height="fit"
              >
                <Text
                  font="secondary-mono"
                  color={mutedColor}
                  wordWrap="whitespace-nowrap"
                >
                  {formatDateTimeLog(run.time_created)}
                </Text>
                <Section
                  flexDirection="row"
                  alignItems="center"
                  gap={0.5}
                  padding={0.5}
                  width="fit"
                  height="fit"
                >
                  {run.kind === "indexing" && run.attempt.is_new_model && (
                    <Tag
                      title={tRuns("newModel.label")}
                      tooltip={tRuns("newModel.tooltip")}
                      color="purple"
                    />
                  )}
                  <Text font="secondary-body" color={mutedColor} maxLines={1}>
                    {identity}
                  </Text>
                  <IdentityIcon size={12} className="stroke-text-02" />
                </Section>
              </Section>
              <Section alignItems="stretch" gap={0} padding={0.5} height="fit">
                <Text
                  font="main-ui-body"
                  color={closed ? "text-03" : "text-04"}
                >
                  {title}
                </Text>
                {description !== null && (
                  <Text font="secondary-body" color={mutedColor} maxLines={3}>
                    {description}
                  </Text>
                )}
              </Section>
            </Section>
          </Section>
          {(trace !== null ||
            warnings > 0 ||
            listsChecks ||
            closed ||
            resolvesRun) && (
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="center"
              gap={1}
              padding={0.5}
              height="fit"
            >
              <Section
                flexDirection="row"
                justifyContent="start"
                alignItems="center"
                gap={1}
                height="fit"
                className={cn("min-w-0 flex-1", closed && "opacity-60")}
                wrap
              >
                {trace !== null && (
                  <Popover onOpenChange={togglePopover("trace")}>
                    <Popover.Trigger asChild>
                      <Tag
                        icon={SvgTextLines}
                        title={t("tags.stackTrace")}
                        size="md"
                        onClick={NOOP}
                      />
                    </Popover.Trigger>
                    <StackTracePopoverContent
                      runId={run.attempt.id}
                      trace={trace}
                    />
                  </Popover>
                )}
                {listsDocs ? (
                  <Popover onOpenChange={togglePopover("items")}>
                    <Popover.Trigger asChild>
                      <Tag
                        icon={WARNING_ICONS.indexing}
                        iconColor={pillIconColor}
                        title={docsLabel}
                        size="md"
                        onClick={NOOP}
                      />
                    </Popover.Trigger>
                    <FailedDocsPopoverContent
                      ccPairId={ccPairId}
                      indexAttemptId={run.attempt.id}
                      canResolve={resolvable}
                      onResolve={onResolve}
                      resolving={resolving}
                    />
                  </Popover>
                ) : run.kind === "checks" && listsChecks ? (
                  <Popover onOpenChange={togglePopover("items")}>
                    <Popover.Trigger asChild>
                      <Tag
                        icon={WARNING_ICONS.checks}
                        iconColor={pillIconColor}
                        title={docsLabel}
                        size="md"
                        onClick={NOOP}
                      />
                    </Popover.Trigger>
                    <CheckRunPopoverContent run={run.attempt} beside />
                  </Popover>
                ) : (
                  warnings > 0 && (
                    <Tag
                      icon={WARNING_ICONS[run.kind]}
                      iconColor={pillIconColor}
                      title={docsLabel}
                      size="md"
                    />
                  )
                )}
              </Section>
              {closed ? (
                <SelectButton
                  variant="select-heavy"
                  state="selected"
                  rightIcon={SvgCheckSquare}
                  size="xs"
                >
                  {t("tags.resolved")}
                </SelectButton>
              ) : (
                resolvesRun && (
                  // Only on hover, focus or an open pill, so an open list reads as its runs. Opacity keeps it in the tab order.
                  <Section
                    width="fit"
                    height="fit"
                    className={cn(
                      "transition-opacity no-hover:opacity-100",
                      !(hovered || focused || selected) && "opacity-0"
                    )}
                  >
                    <Button
                      rightIcon={SvgCheckAll}
                      prominence="tertiary"
                      size="xs"
                      disabled={resolving}
                      onClick={onResolveRun}
                    >
                      {t("actions.resolve")}
                    </Button>
                  </Section>
                )
              )}
            </Section>
          )}
        </Section>
      </Card>
    </Section>
  );
}
