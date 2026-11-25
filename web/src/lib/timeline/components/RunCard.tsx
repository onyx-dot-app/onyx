"use client";

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { IconFunctionComponent } from "@opal/types";
import { Line, Presence, Text } from "@opal/components";
import { SvgSparkle } from "@opal/icons";
import { formatDurationSeconds } from "@opal/time";
import { cn } from "@opal/utils";
import { useTranslations } from "next-intl";
import { useStreamingDuration } from "@/lib/timeline/useStreamingDuration";
import { Section } from "@opal/layouts";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";
import { MemoryTagWithTooltip } from "@/lib/timeline/components/headers/MemoryTagWithTooltip";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { useRevealOnOpen } from "@/lib/chatScroll/hooks";
import {
  RunStepOpenContext,
  type RunStepOpenState,
} from "@/lib/timeline/components/RunStep";
import type {
  TimelineEntryStatus,
  TimelineStepPosition,
} from "@/lib/timeline/types";

export interface RunCardStep {
  id: string;
  status: TimelineEntryStatus;
}

/** What the finished card adds on its right side: a memory change. */
export interface RunCardSummary {
  memoryText?: string | null;
  memoryOperation?: "add" | "update" | null;
  memoryId?: number | null;
  memoryIndex?: number | null;
}

export interface RunCardProps<S extends RunCardStep> {
  /** The run's steps, in arrival order. */
  steps: S[];
  renderStep: (step: S, position: TimelineStepPosition) => React.ReactNode;
  /** Header text while the run works. */
  workingText: string;
  /**
   * Whether the run still works. Defaults to a step that streams; a run can
   * also work between steps, such as while it waits for an approval.
   */
  isActive?: boolean;
  /** Whether the user stopped the run. Defaults to a stopped step. */
  isStopped?: boolean;
  /** Fold the run closed once text follows it. */
  autoCollapse?: boolean;
  /** When the run started, for the live timer. Defaults to its first render. */
  streamingStartTime?: number;
  /** The server's duration, shown for a run that did not work here. */
  durationSeconds?: number;
  /** The header's icon while the run works and once it is done. */
  icon?: IconFunctionComponent;
  /**
   * Play the card's entry when it mounts while its run works. Off for a card
   * that takes the place of a run's own step cards (see AgentTimeline).
   */
  appear?: boolean;
  /** Mount folded, even while the run works. */
  startFolded?: boolean;
  summary?: RunCardSummary;
}

/** The open card's step list scrolls inside this height. */
export const RUN_STEP_LIST_MAX_HEIGHT_CLASS = "max-h-[min(18rem,50dvh)]";

/** Follow an append only when the list was at its end before it. */
export function shouldFollowRunAppend(
  previous: ReadonlyArray<{ readonly id: string }>,
  steps: ReadonlyArray<{ readonly id: string }>,
  distanceFromEnd: number
): boolean {
  return (
    previous.length > 0 &&
    steps.length > previous.length &&
    distanceFromEnd <= 1 &&
    previous.every((step, index) => step.id === steps[index]?.id)
  );
}

function distanceFromEnd(element: HTMLElement): number {
  return element.scrollHeight - element.clientHeight - element.scrollTop;
}

function sameIds(
  a: ReadonlyArray<{ readonly id: string }>,
  b: ReadonlyArray<{ readonly id: string }>
): boolean {
  return (
    a.length === b.length && a.every((step, index) => step.id === b[index]?.id)
  );
}

/**
 * Keeps the step list at its end while new steps arrive, but only when the
 * user was already there. A scroll up stops the follow.
 */
function useFollowAppendedSteps(steps: RunCardStep[], isRunning: boolean) {
  const [list, setList] = useState<HTMLDivElement | null>(null);
  const atEndRef = useRef(true);
  const followRef = useRef(false);
  const previousRef = useRef(steps);
  const lastTopRef = useRef(0);

  useLayoutEffect(() => {
    const previous = previousRef.current;
    previousRef.current = steps;
    // A status update keeps the follow: an appended step still grows in.
    if (sameIds(previous, steps)) return;
    followRef.current =
      isRunning &&
      shouldFollowRunAppend(previous, steps, atEndRef.current ? 0 : Infinity);
    if (followRef.current && list) list.scrollTop = list.scrollHeight;
  }, [steps, isRunning, list]);

  useEffect(() => {
    if (!list) return;
    atEndRef.current = distanceFromEnd(list) <= 1;
    lastTopRef.current = list.scrollTop;
    const content = list.firstElementChild;
    if (!content) return;
    const observer = new ResizeObserver(() => {
      if (followRef.current) list.scrollTop = list.scrollHeight;
      else atEndRef.current = distanceFromEnd(list) <= 1;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [list]);

  const onScroll = useCallback(() => {
    if (!list) return;
    atEndRef.current = distanceFromEnd(list) <= 1;
    // Only a scroll up stops the follow: a step that grows in can leave the
    // list short of its end between two follow scrolls.
    if (list.scrollTop < lastTopRef.current) followRef.current = false;
    lastTopRef.current = list.scrollTop;
  }, [list]);

  return { listRef: setList, onScroll };
}

/**
 * One run of steps as a card, the same in chat and Craft: the run header
 * across the top (working, finished or stopped), and the steps below it on
 * the rail. Every run folds; it is open while it works and folds once text
 * follows it.
 */
export function RunCard<S extends RunCardStep>({
  steps,
  renderStep,
  workingText,
  isActive,
  isStopped,
  autoCollapse = false,
  streamingStartTime,
  durationSeconds,
  icon = SvgSparkle,
  appear = true,
  startFolded = false,
  summary,
}: RunCardProps<S>) {
  const t = useTranslations("chat.messages.timeline");
  const isRunning =
    isActive ?? steps.some((step) => step.status === "streaming");
  const stopped =
    !isRunning &&
    (isStopped ?? steps.some((step) => step.status === "stopped"));
  const [isOpen, setIsOpen] = useState(isRunning && !startFolded);
  // A card that arrives while its run works rises in; a saved run's card
  // appears at once.
  const [arrivedLive] = useState(appear && isRunning);
  // Steps already there when the card mounts show at once; later ones rise
  // in.
  const [initialStepIds] = useState(
    () => new Set(steps.map((step) => step.id))
  );
  const { listRef, onScroll } = useFollowAppendedSteps(steps, isRunning);
  // Kept here, so each step's open state survives a fold of the card.
  const [openStepIds, setOpenStepIds] = useState<ReadonlySet<string>>(
    () => new Set()
  );
  const stepOpenState = useMemo<RunStepOpenState>(
    () => ({
      openIds: openStepIds,
      setOpen: (id, open) =>
        setOpenStepIds((previous) => {
          const next = new Set(previous);
          if (open) next.add(id);
          else next.delete(id);
          return next;
        }),
    }),
    [openStepIds]
  );
  // A card the user folded or opened keeps their choice.
  const userToggled = useRef(false);
  const { rowRef, onToggle } = useRevealOnOpen();
  const toggle = () => {
    userToggled.current = true;
    onToggle(!isOpen);
    setIsOpen(!isOpen);
  };

  // Fold closed once text follows; fire once so a manual re-open sticks.
  const didAutoCollapse = useRef(false);
  useEffect(() => {
    if (autoCollapse && !didAutoCollapse.current) {
      didAutoCollapse.current = true;
      if (!userToggled.current) setIsOpen(false);
    }
  }, [autoCollapse]);

  // Open when the run becomes active again: a run that mounted settled, or a
  // waiting card that folded under text and is reused by the first call.
  // Only on that change, so a later fold sticks.
  const wasRunning = useRef(isRunning);
  useEffect(() => {
    if (isRunning && !wasRunning.current && !userToggled.current) {
      setIsOpen(true);
    }
    wasRunning.current = isRunning;
  }, [isRunning]);

  // A run that works here is timed in the browser; a saved run shows the
  // server's duration.
  const [startedAt, setStartedAt] = useState<number | undefined>(() =>
    isRunning ? (streamingStartTime ?? Date.now()) : undefined
  );
  // A card that mounted settled starts its timer when its run starts here.
  useEffect(() => {
    if (isRunning && startedAt === undefined) {
      setStartedAt(streamingStartTime ?? Date.now());
    }
  }, [isRunning, startedAt, streamingStartTime]);
  const elapsedSeconds = useStreamingDuration(isRunning, startedAt);
  const finishedSeconds =
    startedAt !== undefined ? Math.max(1, elapsedSeconds) : durationSeconds;

  // A run that stopped working with no steps (e.g. a wait for the user that
  // ended) has nothing to show. It leaves through Presence's exit, so it
  // fades out and its height closes, instead of vanishing.
  const visible = steps.length > 0 || isRunning;
  const foldable = steps.length > 0;

  const duration = finishedSeconds
    ? formatDurationSeconds(finishedSeconds)
    : null;
  const headerTitle = isRunning
    ? workingText
    : stopped
      ? duration
        ? t("stoppedDuration.label", { duration })
        : t("interruptedThinking.label")
      : duration
        ? t("thoughtDuration.label", { duration })
        : t("thoughtUnknownDuration.label");

  return (
    <Presence show={visible} appear={arrivedLive} grow>
      <TimelineRoot ref={rowRef}>
        <Line
          // Filled while open; otherwise only on hover, as a step card is.
          filled={isOpen}
          onClick={foldable ? toggle : undefined}
          // The header's own fold button, in every state, so its step count
          // animates as it changes and it lights up with the header.
          rightChildren={
            foldable && (
              <>
                {/* A saved memory's tag, on the right so it never swaps the
                    summary. Shown on a finished card while it is folded. */}
                {summary?.memoryOperation && (
                  <Presence
                    show={!isRunning && !stopped && !isOpen}
                    from="end"
                    width="fit"
                  >
                    <MemoryTagWithTooltip
                      memoryText={summary.memoryText ?? null}
                      memoryOperation={summary.memoryOperation}
                      memoryId={summary.memoryId ?? null}
                      memoryIndex={summary.memoryIndex ?? null}
                    />
                  </Presence>
                )}
                {/* The timer is plain text beside the button: a button label
                    animates its changes, so each tick would flash. */}
                <Presence
                  show={isRunning && isOpen && elapsedSeconds > 0}
                  from="end"
                  width="fit"
                >
                  <div className="px-(--padding-text-4)">
                    <Text
                      as="p"
                      font="secondary-body"
                      color="text-03"
                      wordWrap="whitespace-nowrap"
                    >
                      {formatDurationSeconds(elapsedSeconds)}
                    </Text>
                  </div>
                </Presence>
                {/* The step count is text before the chevron, so the card's
                    chevron lines up with its steps' chevrons. */}
                <div className="px-(--padding-text-4)">
                  <Text
                    as="p"
                    font="secondary-body"
                    color="text-03"
                    wordWrap="whitespace-nowrap"
                  >
                    {t("stepsButton.label", { count: steps.length })}
                  </Text>
                </div>
              </>
            )
          }
          expandable
          expanded={isOpen}
          expandedContent={
            // The steps, 4px apart. A step card
            // inside has no padding of its own, so its title lines up with
            // the card's own title.
            <div
              ref={listRef}
              onScroll={onScroll}
              className={cn(RUN_STEP_LIST_MAX_HEIGHT_CLASS, "overflow-y-auto")}
            >
              <RunStepOpenContext.Provider value={stepOpenState}>
                <Section alignItems="stretch" gap={1} height="auto">
                  {steps.map((step, index) => (
                    // A step that streams in rises in, after the card opens
                    // room for it. Steps already there when the card mounts
                    // (a saved run) appear at once.
                    <Presence
                      key={step.id}
                      appear={isRunning && !initialStepIds.has(step.id)}
                      grow
                    >
                      {renderStep(step, {
                        isFirst: index === 0,
                        isLast: index === steps.length - 1,
                      })}
                    </Presence>
                  ))}
                </Section>
              </RunStepOpenContext.Provider>
            </div>
          }
          // The card's own title, the same header a hoisted run card has.
          // It swaps when the run's state changes (working, stopped, done);
          // while working, a new activity updates the text in place, so the
          // shimmer never restarts.
          icon={stopped && !isRunning ? STEP_ICONS.stopped : icon}
          title={headerTitle}
          titleKey={isRunning ? "working" : stopped ? "stopped" : "done"}
          shimmer={isRunning}
        />
      </TimelineRoot>
    </Presence>
  );
}

export default RunCard;
