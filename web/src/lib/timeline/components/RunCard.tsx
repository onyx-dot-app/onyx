"use client";

import React, { useEffect, useRef, useState } from "react";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Line, Presence, Text } from "@opal/components";
import { SvgSparkle } from "@opal/icons";
import { formatDurationSeconds } from "@opal/time";
import { useTranslations } from "next-intl";
import { useStreamingDuration } from "@/lib/timeline/useStreamingDuration";
import { Section } from "@opal/layouts";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";
import { MemoryTagWithTooltip } from "@/lib/timeline/components/headers/MemoryTagWithTooltip";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { useRevealOnOpen } from "@/lib/chatScroll/hooks";
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
  /** The finished header's text, in place of the duration. */
  doneText?: string | RichStr;
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
  doneText,
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

  const headerTitle = isRunning
    ? workingText
    : stopped
      ? t("interruptedThinking.label")
      : (doneText ??
        (finishedSeconds
          ? t("thoughtDuration.label", {
              duration: formatDurationSeconds(finishedSeconds),
            })
          : t("thoughtUnknownDuration.label")));

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
            <Section alignItems="stretch" gap={1} height="auto">
              {steps.map((step, index) => (
                // A step that streams in rises in, after the card opens room
                // for it. Steps already there when the card mounts (a saved
                // run) appear at once.
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
