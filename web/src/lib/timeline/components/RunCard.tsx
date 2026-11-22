"use client";

import React, { useEffect, useRef, useState } from "react";
import { Line, Presence, Text } from "@opal/components";
import { formatDurationSeconds } from "@opal/time";
import { useTranslations } from "next-intl";
import { useStreamingDuration } from "@/lib/timeline/useStreamingDuration";
import { Section } from "@opal/layouts";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";
import { StreamingHeader } from "@/lib/timeline/components/headers/StreamingHeader";
import {
  CompletedHeader,
  MemoryTagWithTooltip,
  type CompletedHeaderProps,
} from "@/lib/timeline/components/headers/CompletedHeader";
import { StoppedHeader } from "@/lib/timeline/components/headers/StoppedHeader";
import type {
  TimelineEntryStatus,
  TimelineStepPosition,
} from "@/lib/timeline/types";

export interface RunCardStep {
  id: string;
  status: TimelineEntryStatus;
}

/** What the finished header can add: generated images, a memory change. */
export type RunCardSummary = Pick<
  CompletedHeaderProps,
  | "generatedImageCount"
  | "isMemoryOnly"
  | "memoryText"
  | "memoryOperation"
  | "memoryId"
  | "memoryIndex"
>;

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
  summary,
}: RunCardProps<S>) {
  const t = useTranslations("chat.messages.timeline");
  const isRunning =
    isActive ?? steps.some((step) => step.status === "streaming");
  const stopped =
    !isRunning &&
    (isStopped ?? steps.some((step) => step.status === "stopped"));
  const [isOpen, setIsOpen] = useState(isRunning);
  // A card that arrives while its run works rises in; a saved run's card
  // appears at once.
  const [arrivedLive] = useState(isRunning);
  // A card the user folded or opened keeps their choice.
  const userToggled = useRef(false);
  const toggle = () => {
    userToggled.current = true;
    setIsOpen((prev) => !prev);
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

  // A run that stopped working with no steps (e.g. "Thinking..." before a
  // text-only answer) has nothing to show. It leaves through Presence's exit,
  // so it fades out and its height closes, instead of vanishing.
  const visible = steps.length > 0 || isRunning;
  const foldable = steps.length > 0;

  return (
    <Presence show={visible} appear={arrivedLive} grow>
      <TimelineRoot>
        <Line
          flavour="card"
          filled={isRunning || isOpen}
          onClick={foldable ? toggle : undefined}
          // The header's own fold button, in every state, so its step count
          // animates as it changes and it lights up with the header.
          foldLabel={
            foldable
              ? t("stepsButton.label", { count: steps.length })
              : undefined
          }
          rightChildren={
            foldable && (
              <>
                {/* A saved memory's tag, on the right so it never swaps the
                    summary. Shown on a finished card while it is folded. */}
                {summary?.memoryOperation && !summary.isMemoryOnly && (
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
              </>
            )
          }
          expandable
          expanded={isOpen}
          expandedContent={
            // The steps, 0.25rem apart.
            <Section alignItems="stretch" gap={1} height="auto">
              {steps.map((step, index) => (
                // A step that streams in rises in, after the card opens room
                // for it. Steps already there when the card mounts (a saved
                // run) appear at once.
                <Presence key={step.id} appear={isRunning} grow>
                  {renderStep(step, {
                    isFirst: index === 0,
                    isLast: index === steps.length - 1,
                  })}
                </Presence>
              ))}
            </Section>
          }
        >
          {/* The header swaps when the run's state changes: working,
              stopped or done. While working, a new activity ("Thinking..."
              to "Searching...") updates the text in place, so the shimmer
              never restarts. */}
          <Presence.Swap
            swapKey={isRunning ? "working" : stopped ? "stopped" : "done"}
          >
            {isRunning ? (
              <StreamingHeader headerText={workingText} />
            ) : stopped ? (
              <StoppedHeader />
            ) : (
              <CompletedHeader
                isExpanded={isOpen}
                processingDurationSeconds={finishedSeconds}
                {...summary}
              />
            )}
          </Presence.Swap>
        </Line>
      </TimelineRoot>
    </Presence>
  );
}

export default RunCard;
