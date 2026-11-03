"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  OverflowText,
  Popover,
  Tag,
  Badge,
  Tooltip,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgCheckSquare,
  SvgFiles,
  SvgHistory,
  SvgRefreshCw,
  SvgTextLines,
  SvgXCircle,
  SvgXOctagon,
} from "@opal/icons";
import type {
  CardColor,
  IconFunctionComponent,
  RichStr,
  StatusVariants,
} from "@opal/types";
import { cn } from "@opal/utils";
import type { CCPairRef, CCPairRun } from "@/lib/connectors/types";
import {
  runKey,
  sectionResolves,
  type ActivitySection,
} from "@/lib/connectors/ccPair/hooks";
import { getSourceMetadata } from "@/lib/connectors/utils";
import { formatDateTimeLog } from "@/lib/dateUtils";
import CheckRunPopoverContent from "@/views/admin/connectors/ConnectorDetailPage/CheckRunPopover";
import { closedBySupersede } from "@/views/admin/connectors/ConnectorDetailPage/closedRun";
import FailedDocsPopoverContent from "@/views/admin/connectors/ConnectorDetailPage/FailedDocsPopover";
import StackTracePopoverContent from "@/views/admin/connectors/ConnectorDetailPage/StackTracePopover";
import type { PopoverPlacement } from "@/views/admin/connectors/ConnectorDetailPage/popoverPlacement";
import { runKindLabelKey } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import {
  isActive,
  runErrorMessage,
  runKindIcon,
  runMinutes,
  runMoved,
  runTrace,
  runWarnings,
} from "@/views/admin/connectors/ConnectorDetailPage/RunRow";

// A Badge is clickable only with an onClick, and the popover trigger around it handles the click.
const NOOP = () => {};

interface SectionStyle {
  color: CardColor;
  icon: IconFunctionComponent;
  stroke: string;
  closedStroke: string;
  /** The 1px edge a hovered, selected or outlined card takes. */
  outline: string;
}

const SECTION_STYLE = {
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
  running: {
    color: "background-tint-00",
    icon: IconLoader,
    stroke: "stroke-status-info-05",
    closedStroke: "stroke-text-02",
    outline: "outline-border-01",
  },
  success: {
    color: "background-tint-00",
    icon: SvgCheckCircle,
    stroke: "stroke-status-success-05",
    closedStroke: "stroke-status-success-02",
    outline: "outline-border-01",
  },
  canceled: {
    color: "background-tint-00",
    icon: SvgXCircle,
    stroke: "stroke-text-03",
    closedStroke: "stroke-text-02",
    outline: "outline-border-01",
  },
} satisfies Record<ActivitySection, SectionStyle>;

type CardState =
  | "failed"
  | "running"
  | "stopped"
  | "errors"
  | "resolved"
  | "inProgress"
  | "canceled"
  | "succeeded";

/** The title's state key: how the run stands in its section. A closed card reads as it did when open, except a run with errors that Retry or an admin resolved, which says so. */
function cardState(
  run: CCPairRun,
  section: ActivitySection,
  resolved: boolean
): CardState {
  switch (section) {
    case "failures":
      return "failed";
    case "errors": {
      if (resolved) return "resolved";
      if (isActive(run)) return "running";
      const stopped =
        run.attempt.status === "canceled" ||
        run.attempt.status === "interrupted";
      return stopped ? "stopped" : "errors";
    }
    case "running":
      return "inProgress";
    case "success":
      return "succeeded";
    case "canceled":
      return "canceled";
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

type EntityKind = "indexing" | "pruning" | "checks";

const ENTITY_CHIP_ICONS = {
  indexing: SvgFiles,
  pruning: SvgFiles,
  checks: SvgXOctagon,
} satisfies Record<EntityKind, IconFunctionComponent>;

/** The kind whose failed entities a chip counts. A sync chip counts failed users or groups, which no sync records, so syncs have none. */
function entityKind(run: CCPairRun): EntityKind | null {
  switch (run.kind) {
    case "indexing":
    case "pruning":
    case "checks":
      return run.kind;
    case "doc_permission_sync":
    case "group_sync":
      return null;
  }
}

/** The chip's label key. An index run's errors can be whole sources (a space, a drive), and only its open errors say which, so it reads "items" unless every open error is a document. */
function entityLabelKey(
  run: CCPairRun,
  kind: EntityKind
): `tags.${EntityKind | "indexingItems"}` {
  if (run.kind !== "indexing") return `tags.${kind}`;
  const { open_error_count, open_doc_error_count } = run.attempt;
  const allDocs =
    open_error_count > 0 && open_error_count === open_doc_error_count;
  return allDocs ? "tags.indexing" : "tags.indexingItems";
}

function statusStroke(
  active: boolean,
  closed: boolean,
  style: SectionStyle
): string {
  if (active) return "stroke-status-info-05";
  return closed ? style.closedStroke : style.stroke;
}

function cardColor(
  closed: boolean,
  hovered: boolean,
  section: ActivitySection,
  style: SectionStyle
): CardColor {
  if (closed) return "background-tint-01";
  if (hovered && section === "errors") return "background-tint-02";
  return style.color;
}

interface PopoverChipProps {
  icon: IconFunctionComponent;
  iconColor?: StatusVariants;
  title: string | RichStr;
  /** What the chip opens. Without it the chip is plain. */
  popover: React.ReactNode | null;
  /** Hangs the popover from the card rather than the chip. */
  anchor: React.ReactNode;
  onOpenChange: (open: boolean) => void;
}

/** A footer chip that opens its popover on click. */
function PopoverChip({
  icon,
  iconColor,
  title,
  popover,
  anchor,
  onOpenChange,
}: PopoverChipProps) {
  if (popover === null) {
    return <Tag icon={icon} iconColor={iconColor} title={title} />;
  }
  return (
    <Popover onOpenChange={onOpenChange}>
      <Popover.Trigger asChild>
        <Tag icon={icon} iconColor={iconColor} title={title} onClick={NOOP} />
      </Popover.Trigger>
      {anchor}
      {popover}
    </Popover>
  );
}

export interface ActivityCardProps {
  ccPairId: number;
  run: CCPairRun;
  section: ActivitySection;
  /** The run is resolved or superseded: it keeps its section's icon, with every element faded. */
  closed: boolean;
  /** Shows the pair's logo in place of the run's kind, for a feed across pairs. */
  connector?: CCPairRef;
  /** Whether the viewer may re-fetch single documents of this pair. */
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
  /** The pointer entered or left the card. */
  onHoverChange?: (hovered: boolean) => void;
  /** Picked from the chart: the card scrolls into view and lifts. */
  focused?: boolean;
  /** A hovered chart line holds the run, so the card takes its hover edge. */
  outlined?: boolean;
}

/** One run in an activity list: when, which kind or pair, how it stands in its section, its trace and failed items, and what the viewer may do about them. */
export default function ActivityCard({
  ccPairId,
  run,
  section,
  closed,
  connector,
  canResolve,
  canResolveRuns,
  onResolve,
  onResolveRun,
  resolving,
  popoverPlacement = "beside",
  onHoverChange,
  focused = false,
  outlined = false,
}: ActivityCardProps) {
  const t = useTranslations("admin.connector.activity");
  const rootRef = useRef<HTMLDivElement>(null);
  // A popover below the card hangs from the card, not from its pill: a span
  // covering the card is the anchor. It sits after the trigger in each
  // popover so its ref registers last and stays the anchor.
  const anchor = popoverPlacement === "below" && (
    <Popover.Anchor asChild>
      <span aria-hidden className="pointer-events-none absolute -inset-1" />
    </Popover.Anchor>
  );
  const [hovered, setHovered] = useState(false);
  const [focusWithin, setFocusWithin] = useState(false);
  const [openPopover, setOpenPopover] = useState<"trace" | "items" | null>(
    null
  );
  useEffect(() => {
    if (focused) {
      rootRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [focused]);
  const selected = openPopover !== null;
  const togglePopover = (popover: "trace" | "items") => (open: boolean) =>
    setOpenPopover((current) =>
      open ? popover : current === popover ? null : current
    );
  const active = isActive(run);
  const superseded = closed && closedBySupersede(run);
  const state = cardState(run, section, closed && !superseded);
  const style: SectionStyle = SECTION_STYLE[section];
  const StatusIcon = active ? IconLoader : style.icon;
  const minutes = runMinutes(run);
  const chipKind = entityKind(run);
  // Counts resolved entities too, so the chip keeps what the run failed on.
  const entities = chipKind === null ? 0 : runWarnings(run);
  const trace = runTrace(run);
  const openable = sectionResolves(section);
  const openDocs =
    run.kind === "indexing" ? run.attempt.open_doc_error_count : 0;
  // Only an index run resolves while running, since other kinds count failures without a time and the server refuses them until they finish.
  const resolvesRun =
    openable &&
    !closed &&
    canResolveRuns &&
    (!active || run.kind === "indexing");
  // A run still going can fail the same documents again, so only a finished one retries them.
  const retriesDocs =
    openable && !closed && !active && canResolve && openDocs > 0;
  const showsActions = resolvesRun || retriesDocs;
  const hasChips = trace !== null || entities > 0;
  const revealed = hovered || focusWithin || selected;
  const edged = hovered || selected || outlined;
  const lifted = selected || focused;
  const mutedColor = closed ? "text-02" : "text-03";

  // A failure, superseded or not, titles with the error's first sentence and describes with the rest. A run with errors reports what it still did.
  let description: string | null = null;
  let title = t(`title.${run.kind}.${state}`);
  if (section === "failures") {
    const message = runErrorMessage(run);
    const split = message ? splitReason(message) : null;
    if (split !== null && split.reason !== "") {
      title = t(`title.${run.kind}.failedWith`, { reason: split.reason });
      description = split.rest;
    } else if (chipKind === "checks" && entities > 0) {
      description = t("description.checksFailed", { count: entities });
    }
  } else if (minutes !== null) {
    description = t(`description.${run.kind}`, {
      count: runMoved(run),
      minutes,
    });
  }
  const chipIconColor = closed ? undefined : "warning";
  const ClosedIcon = superseded ? SvgHistory : SvgCheckSquare;

  // A pruning run records how many documents failed, not which, so its chip opens nothing.
  function entityPopover(): React.ReactNode | null {
    switch (run.kind) {
      case "indexing":
        return (
          <FailedDocsPopoverContent
            ccPairId={ccPairId}
            indexAttemptId={run.attempt.id}
            canResolve={canResolve && openDocs > 0}
            onResolve={onResolve}
            resolving={resolving}
            placement={popoverPlacement}
          />
        );
      case "checks":
        return (
          <CheckRunPopoverContent
            run={run.attempt}
            placement={popoverPlacement}
          />
        );
      default:
        return null;
    }
  }

  const resolveButton = retriesDocs ? (
    <Button
      icon={SvgCheckSquare}
      prominence="tertiary"
      size="md"
      tooltip={t("actions.resolveWithoutRetry")}
      aria-label={t("actions.resolveWithoutRetry")}
      disabled={resolving}
      onClick={onResolveRun}
    />
  ) : (
    <Button
      rightIcon={SvgCheckSquare}
      prominence="internal"
      size="sm"
      disabled={resolving}
      onClick={onResolveRun}
    >
      {t("actions.resolve")}
    </Button>
  );

  // The outline draws the edge inside the card, so hovering does not shift the list.
  return (
    <Section
      ref={rootRef}
      alignItems="stretch"
      height="fit"
      className={cn(
        "rounded-08 -outline-offset-1",
        edged && ["outline-1 outline-solid", style.outline]
      )}
      onPointerEnter={() => {
        setHovered(true);
        onHoverChange?.(true);
      }}
      onPointerLeave={() => {
        setHovered(false);
        onHoverChange?.(false);
      }}
      onFocus={() => setFocusWithin(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setFocusWithin(false);
        }
      }}
      data-testid="activity-card"
      data-run-key={runKey(run)}
    >
      <Card
        color={cardColor(closed, hovered, section, style)}
        border="none"
        rounding={2}
        padding={1}
        shadow={lifted ? "md" : "none"}
      >
        <Section alignItems="stretch" gap={0} height="fit" className="relative">
          <Section
            flexDirection="row"
            alignItems="start"
            gap={1}
            padding={1}
            height="fit"
          >
            <Section padding={0.5} width="fit" height="fit">
              <StatusIcon
                size={16}
                className={statusStroke(active, closed, style)}
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
                <ActivityIdentity
                  run={run}
                  connector={connector}
                  closed={closed}
                  mutedColor={mutedColor}
                />
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
          {openable &&
            (hasChips || showsActions || closed) && (
              // A card with no chips shows its footer only with its actions, so it draws no empty band. Clipped, the actions stay in the tab order.
              <Section
                alignItems="stretch"
                height="fit"
                className={cn(
                  !hasChips &&
                    !closed &&
                    !revealed &&
                    "max-h-0 overflow-hidden no-hover:max-h-none"
                )}
              >
                <Section
                  flexDirection="row"
                  justifyContent="between"
                  gap={1}
                  padding={0.5}
                  height="fit"
                >
                  <Section
                    flexDirection="row"
                    justifyContent="start"
                    gap={1}
                    height="fit"
                    className={cn("min-w-0 flex-1", closed && "opacity-60")}
                    wrap
                  >
                    {trace !== null && (
                      <PopoverChip
                        icon={SvgTextLines}
                        title={t("tags.stackTrace")}
                        anchor={anchor}
                        onOpenChange={togglePopover("trace")}
                        popover={
                          <StackTracePopoverContent
                            runId={run.attempt.id}
                            trace={trace}
                            placement={popoverPlacement}
                          />
                        }
                      />
                    )}
                    {chipKind !== null && entities > 0 && (
                      <PopoverChip
                        icon={ENTITY_CHIP_ICONS[chipKind]}
                        iconColor={chipIconColor}
                        title={t(entityLabelKey(run, chipKind), {
                          count: entities,
                        })}
                        anchor={anchor}
                        onOpenChange={togglePopover("items")}
                        popover={entityPopover()}
                      />
                    )}
                  </Section>
                  {closed ? (
                    <Section
                      flexDirection="row"
                      gap={0.5}
                      width="fit"
                      height="fit"
                    >
                      <Text font="secondary-action" color="text-03">
                        {t(superseded ? "tags.superseded" : "tags.resolved")}
                      </Text>
                      <ClosedIcon size={16} className="stroke-text-03" />
                    </Section>
                  ) : (
                    showsActions && (
                      // Only on hover, focus or an open pill, so an open list reads as its runs. Opacity keeps them in the tab order.
                      <Section
                        flexDirection="row"
                        gap={0.5}
                        width="fit"
                        height="fit"
                        className={cn(
                          "transition-opacity no-hover:opacity-100",
                          !revealed && "opacity-0"
                        )}
                      >
                        {retriesDocs && (
                          <Button
                            rightIcon={SvgRefreshCw}
                            prominence="internal"
                            size="sm"
                            disabled={resolving}
                            onClick={() => onResolve(null)}
                          >
                            {t("actions.retryDocs")}
                          </Button>
                        )}
                        {resolvesRun && resolveButton}
                      </Section>
                    )
                  )}
                </Section>
              </Section>
            )}
        </Section>
      </Card>
    </Section>
  );
}

interface ActivityIdentityProps {
  run: CCPairRun;
  connector: CCPairRef | undefined;
  closed: boolean;
  mutedColor: "text-02" | "text-03";
}

/** Which run this is: the pair's logo with its name as tooltip across pairs, the run's kind on one pair's page. */
function ActivityIdentity({
  run,
  connector,
  closed,
  mutedColor,
}: ActivityIdentityProps) {
  const tRuns = useTranslations("admin.connector.runs");
  const newModel = run.kind === "indexing" && run.attempt.is_new_model && (
    <Tooltip tooltip={tRuns("newModel.tooltip")} side="top">
      <Badge title={tRuns("newModel.label")} color="info" />
    </Tooltip>
  );
  if (connector !== undefined) {
    const Logo = getSourceMetadata(connector.source).icon;
    return (
      <Section
        flexDirection="row"
        justifyContent="end"
        gap={0.5}
        width="fit"
        height="fit"
        className={cn(closed && "opacity-50")}
      >
        {newModel}
        <Tooltip tooltip={connector.name} side="top">
          <Section padding={0.5} width="fit" height="fit">
            <Logo size={12} />
          </Section>
        </Tooltip>
      </Section>
    );
  }
  const KindIcon = runKindIcon(run);
  // The kind shrinks before the timestamp, so a long label truncates.
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      gap={0.5}
      padding={0.5}
      height="fit"
      className="min-w-0"
    >
      {newModel}
      <OverflowText font="secondary-body" color={mutedColor}>
        {tRuns(`kinds.${runKindLabelKey(run)}`)}
      </OverflowText>
      <KindIcon size={12} className="shrink-0 stroke-text-02" />
    </Section>
  );
}
