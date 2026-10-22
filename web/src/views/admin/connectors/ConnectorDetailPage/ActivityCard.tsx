"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  OverflowText,
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
  SvgClock,
  SvgFiles,
  SvgHistory,
  SvgRefreshCw,
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
import { closedBySupersede } from "@/views/admin/connectors/ConnectorDetailPage/closedRun";
import FailedDocsPopoverContent from "@/views/admin/connectors/ConnectorDetailPage/FailedDocsPopover";
import StackTracePopoverContent from "@/views/admin/connectors/ConnectorDetailPage/StackTracePopover";
import type { PopoverPlacement } from "@/views/admin/connectors/ConnectorDetailPage/popoverPlacement";
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
  | "queued"
  | "inProgress"
  | "canceled"
  | "succeeded";

/** The title's state key: how the run stands in its group. A closed card reads as it did when open, except a run with errors that Retry or an admin resolved, which says so. */
function cardState(
  run: CCPairRun,
  group: ActivityGroup,
  resolved: boolean
): CardState {
  const stopped =
    run.attempt.status === "canceled" || run.attempt.status === "interrupted";
  switch (group) {
    case "failures":
      return "failed";
    case "errors":
      if (resolved) return "resolved";
      if (isActive(run)) return "running";
      return stopped ? "stopped" : "errors";
    case "other":
      if (run.attempt.status === "not_started") return "queued";
      if (isActive(run)) return "inProgress";
      return stopped ? "canceled" : "succeeded";
  }
}

interface StatusIcon {
  icon: IconFunctionComponent;
  stroke: string;
}

/** A queued run waits on the Scheduled tag's clock, a live one spins, any other shows its group's icon. */
function statusIcon(
  state: CardState,
  active: boolean,
  group: ActivityGroup,
  closed: boolean
): StatusIcon {
  if (state === "queued") {
    return { icon: SvgClock, stroke: "stroke-theme-purple-05" };
  }
  if (active) return { icon: IconLoader, stroke: "stroke-status-info-05" };
  const style = GROUP_STYLE[group];
  return {
    icon: style.icon,
    stroke: closed ? style.closedStroke : style.stroke,
  };
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
  /** Whether the viewer may re-fetch single documents of this pair. Otherwise the retry actions hide, except a disabled Retry when `canResolveRuns` holds. */
  canResolve: boolean;
  /** Whether the viewer may mark the run resolved. */
  canResolveRuns: boolean;
  /** Resolves these errors of the run by a targeted reindex, or every open one when `null`. */
  onResolve: (errorIds: number[] | null) => void;
  /** Marks the run resolved without a reindex. */
  onResolveRun: () => void;
  /** A resolve is in flight, so the resolve actions wait for it. */
  resolving: boolean;
  /** Where a pill's popover opens: beside the card, or below it with its end at the card's end. Default: beside. */
  popoverPlacement?: PopoverPlacement;
}

/** One run in an activity list: when, which kind, how it stands in its group, its trace and failed items. */
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
  popoverPlacement = "beside",
}: ActivityCardProps) {
  const t = useTranslations("admin.connector.activity");
  // A popover below the card hangs from the card, not from its pill: a span
  // covering the card is the anchor. It sits after the trigger in each
  // popover so its ref registers last and stays the anchor.
  const anchor = popoverPlacement === "below" && (
    <Popover.Anchor asChild>
      <span aria-hidden className="pointer-events-none absolute -inset-1" />
    </Popover.Anchor>
  );
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
  const superseded = closed && closedBySupersede(run);
  const resolved = closed && !superseded;
  const state = cardState(run, group, resolved);
  const style = GROUP_STYLE[group];
  const { icon: StatusIcon, stroke: statusStroke } = statusIcon(
    state,
    active,
    group,
    closed
  );
  const IdentityIcon =
    connector === undefined
      ? RUN_KIND_ICONS[run.kind]
      : getSourceMetadata(connector.source).icon;
  const identity =
    connector === undefined ? tRuns(`kinds.${run.kind}`) : connector.name;
  const minutes = runMinutes(run);
  const warnings = runWarnings(run);
  const trace = runTrace(run);
  // The list holds every open error of an index attempt. Only its documents can be retried.
  const indexing = run.kind === "indexing";
  const openErrors = indexing ? run.attempt.open_error_count : 0;
  const openDocs = indexing ? run.attempt.open_doc_error_count : 0;
  const listsErrors = openErrors > 0;
  const resolvable = canResolve && openDocs > 0;
  // The viewer could resolve, but the connector cannot re-fetch single documents. The button stays, disabled, to say so.
  const resolveUnsupported = openDocs > 0 && canResolveRuns && !canResolve;
  // A failed check run lists what failed instead of a stack trace.
  const listsChecks = run.kind === "checks" && warnings > 0;
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
  // A resolved card counts the items it resolved, whole entities included. A superseded one keeps the pill it had when open, only faded.
  const docsLabel =
    resolved && run.kind !== "checks"
      ? t("tags.resolvedDocs", { count: warnings })
      : !listsErrors
        ? t(`tags.${run.kind}`, { count: warnings })
        : openErrors > openDocs
          ? t("tags.indexingItems", { count: openErrors })
          : t("tags.indexing", { count: openDocs });

  const pillIconColor = closed ? undefined : "orange";

  // The outline draws the edge inside the card, so hovering does not shift the list.
  return (
    <Section
      alignItems="stretch"
      height="fit"
      className={cn(
        "rounded-08 -outline-offset-1",
        (hovered || selected) && "outline-1 outline-solid",
        (hovered || selected) && style.outline
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
        <Section alignItems="stretch" gap={0} height="fit" className="relative">
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
              <StatusIcon size={16} className={statusStroke} />
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
                {/* The identity shrinks before the timestamp, so a long connector name truncates with its tooltip. */}
                <Section
                  flexDirection="row"
                  justifyContent="end"
                  alignItems="center"
                  gap={0.5}
                  padding={0.5}
                  height="fit"
                  className="min-w-0"
                >
                  {run.kind === "indexing" && run.attempt.is_new_model && (
                    <Tag
                      title={tRuns("newModel.label")}
                      tooltip={tRuns("newModel.tooltip")}
                      color="purple"
                    />
                  )}
                  <OverflowText font="secondary-body" color={mutedColor}>
                    {identity}
                  </OverflowText>
                  <IdentityIcon size={12} className="shrink-0 stroke-text-02" />
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
                    {anchor}
                    <StackTracePopoverContent
                      runId={run.attempt.id}
                      trace={trace}
                      placement={popoverPlacement}
                    />
                  </Popover>
                )}
                {listsErrors ? (
                  <>
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
                      {anchor}
                      <FailedDocsPopoverContent
                        ccPairId={ccPairId}
                        indexAttemptId={run.attempt.id}
                        canResolve={resolvable}
                        onResolve={onResolve}
                        resolving={resolving}
                        placement={popoverPlacement}
                      />
                    </Popover>
                    {/* One click re-indexes every open failed document, without opening the list. */}
                    {(resolvable || resolveUnsupported) && !closed && (
                      <Button
                        rightIcon={SvgRefreshCw}
                        prominence="tertiary"
                        size="xs"
                        disabled={resolving || resolveUnsupported}
                        tooltip={t(
                          resolveUnsupported
                            ? "docs.resolveAllUnsupported"
                            : "docs.resolveAllTooltip"
                        )}
                        onClick={() => onResolve(null)}
                      >
                        {t("docs.retry", { count: openDocs })}
                      </Button>
                    )}
                  </>
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
                    {anchor}
                    <CheckRunPopoverContent
                      run={run.attempt}
                      placement={popoverPlacement}
                    />
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
                  rightIcon={superseded ? SvgHistory : SvgCheckSquare}
                  size="xs"
                >
                  {t(superseded ? "tags.superseded" : "tags.resolved")}
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
