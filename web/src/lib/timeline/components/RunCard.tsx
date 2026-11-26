"use client";

import React, {
  useCallback,
  useEffect,
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
import { useRevealOnOpen } from "@/lib/chatScroll/hooks";
import {
  findRunStepRow,
  RunStepOpenContext,
  type RunStepOpenState,
  useRunStepOpenState,
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
  /**
   * Mount open, as the user's choice: it starts open even when the run
   * settled, and the fold under text leaves it open.
   */
  startOpen?: boolean;
  summary?: RunCardSummary;
  /** The run's open step ids, when the run also shows its steps elsewhere
   * (AgentTimeline's hoisted step cards). Defaults to the card's own. */
  stepOpenState?: RunStepOpenState;
}

/** The open card's step list scrolls inside this height. */
export const RUN_STEP_LIST_MAX_HEIGHT_CLASS = "max-h-[min(18rem,50dvh)]";

function distanceFromEnd(element: HTMLElement): number {
  return element.scrollHeight - element.clientHeight - element.scrollTop;
}

/**
 * Scrolls the step list as its content grows. While the run works and the
 * user is at the end, the list stays at the end. Otherwise it keeps the step
 * the user last opened in view. A scroll up stops both.
 */
function useStepListScroll(isRunning: boolean) {
  const [list, setList] = useState<HTMLDivElement | null>(null);
  const runningRef = useRef(isRunning);
  useEffect(() => {
    runningRef.current = isRunning;
  }, [isRunning]);
  const atEndRef = useRef(true);
  const lastTopRef = useRef(0);
  const revealIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!list) return;
    lastTopRef.current = list.scrollTop;
    const content = list.firstElementChild;
    if (!content) return;
    const observer = new ResizeObserver(() => {
      if (runningRef.current && atEndRef.current) {
        list.scrollTop = list.scrollHeight;
        // Recorded now, so a user scroll before the scroll event still reads
        // as a scroll up.
        lastTopRef.current = list.scrollTop;
        return;
      }
      const row =
        revealIdRef.current === null
          ? null
          : findRunStepRow(list, revealIdRef.current);
      if (!row) return;
      const rowBox = row.getBoundingClientRect();
      const listBox = list.getBoundingClientRect();
      const delta = Math.min(
        rowBox.bottom - listBox.bottom,
        rowBox.top - listBox.top
      );
      if (delta > 0) {
        list.scrollTop += delta;
        lastTopRef.current = list.scrollTop;
      }
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [list]);

  const onScroll = useCallback(() => {
    if (!list) return;
    // Only a scroll up leaves the end: a growing step can leave the list
    // short of its end between two follow scrolls.
    // A row that closes at the end clamps the scroll down; that is no
    // scroll up, so the end is checked first.
    if (distanceFromEnd(list) <= 1) {
      atEndRef.current = true;
    } else if (list.scrollTop < lastTopRef.current) {
      atEndRef.current = false;
      revealIdRef.current = null;
    }
    lastTopRef.current = list.scrollTop;
  }, [list]);

  // Opening a step stops the follow until the user scrolls back to the end.
  // Closing one at the end follows again: no scroll happens to say so.
  const reveal = useCallback(
    (id: string | null) => {
      revealIdRef.current = id;
      if (id !== null) atEndRef.current = false;
      else if (list && distanceFromEnd(list) <= 1) atEndRef.current = true;
    },
    [list]
  );

  return { listRef: setList, onScroll, reveal };
}

/**
 * One run of steps as a card, the same in chat and Craft: the run header
 * across the top (working or finished), and the steps below it on the rail.
 * A stopped run reads as finished: the answer already says it stopped. Every run folds; it is open while it works and folds once text
 * follows it.
 */
export function RunCard<S extends RunCardStep>({
  steps,
  renderStep,
  workingText,
  isActive,
  autoCollapse = false,
  streamingStartTime,
  durationSeconds,
  icon = SvgSparkle,
  appear = true,
  startFolded = false,
  startOpen = false,
  summary,
  stepOpenState: sharedOpenState,
}: RunCardProps<S>) {
  const t = useTranslations("chat.messages.timeline");
  const isRunning =
    isActive ?? steps.some((step) => step.status === "streaming");
  const [isOpen, setIsOpen] = useState(
    startOpen || (isRunning && !startFolded)
  );
  // A card that arrives while its run works rises in; a saved run's card
  // appears at once.
  const [arrivedLive] = useState(appear && isRunning);
  // Steps already there when the card mounts show at once; later ones rise
  // in.
  const [initialStepIds] = useState(
    () => new Set(steps.map((step) => step.id))
  );
  const { listRef, onScroll, reveal } = useStepListScroll(isRunning);
  const { rowRef, onToggle } = useRevealOnOpen();
  // Kept here, so each step's open state survives a fold of the card.
  const ownOpenState = useRunStepOpenState();
  const { openIds, setOpen } = sharedOpenState ?? ownOpenState;
  const stepOpenState = useMemo<RunStepOpenState>(
    () => ({
      openIds,
      contained: true,
      setOpen: (id, open) => {
        // The list keeps an opened step in view, and the chat the card.
        reveal(open ? id : null);
        onToggle(open);
        setOpen(id, open);
      },
    }),
    [openIds, setOpen, reveal, onToggle]
  );
  // A card that mounts with an open step (a handover) keeps the latest one
  // in view.
  const [initialOpenId] = useState(() => Array.from(openIds).at(-1));
  useEffect(() => {
    if (initialOpenId !== undefined) reveal(initialOpenId);
  }, [initialOpenId, reveal]);
  // A card the user folded or opened keeps their choice.
  const userToggled = useRef(startOpen);
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
                  <Presence show={!isRunning && !isOpen} from="end" width="fit">
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
          // It swaps when the run's state changes (working, done);
          // while working, a new activity updates the text in place, so the
          // shimmer never restarts.
          icon={icon}
          title={headerTitle}
          titleKey={isRunning ? "working" : "done"}
          shimmer={isRunning}
        />
      </TimelineRoot>
    </Presence>
  );
}

export default RunCard;
