"use client";

import React, { useEffect, useRef, useState } from "react";
import { Button, Fold, Presence, Text } from "@opal/components";
import { SvgExpand, SvgFold } from "@opal/icons";
import { formatDurationSeconds } from "@opal/time";
import { useTranslations } from "next-intl";
import { useStreamingDuration } from "@/lib/timeline/useStreamingDuration";
import { Section } from "@opal/layouts";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";
import {
  RunCardSurface,
  TimelineHeaderRow,
} from "@/lib/timeline/components/primitives/TimelineHeaderRow";
import { StreamingHeader } from "@/lib/timeline/components/headers/StreamingHeader";
import {
  CompletedHeader,
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
  /** How long the run took, when the server knows. Otherwise it is timed. */
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
  const toggle = () => setIsOpen((prev) => !prev);

  // Fold closed once text follows; fire once so a manual re-open sticks.
  const didAutoCollapse = useRef(false);
  useEffect(() => {
    if (autoCollapse && !didAutoCollapse.current) {
      didAutoCollapse.current = true;
      setIsOpen(false);
    }
  }, [autoCollapse]);

  // A run that works here is timed; a saved run has no duration.
  const [startedAt] = useState<number | undefined>(() =>
    isRunning ? (streamingStartTime ?? Date.now()) : undefined
  );
  // The live timer; the server's duration, when it has one, stops it.
  const elapsedSeconds = useStreamingDuration(
    durationSeconds === undefined,
    startedAt,
    durationSeconds
  );

  const [timedSeconds, setTimedSeconds] = useState(0);
  useEffect(() => {
    if (!isRunning && startedAt !== undefined) {
      setTimedSeconds(Math.max(1, Math.round((Date.now() - startedAt) / 1000)));
    }
  }, [isRunning, startedAt]);

  if (steps.length === 0 && !isRunning) return null;

  const foldable = steps.length > 0;

  return (
    <Presence appear={arrivedLive} grow>
      <TimelineRoot>
        <RunCardSurface interactive={foldable} tinted={isRunning || isOpen}>
          {/* Flat: the header, then each step, 0.25rem apart.
            The gap closes with the folds, so a folded card keeps none. */}
          <Section
            alignItems="stretch"
            gap={isOpen ? 1 : 0}
            height="auto"
            className="transition-[row-gap] duration-150"
          >
            <TimelineHeaderRow onClick={foldable ? toggle : undefined}>
              {/* Working, finished and stopped titles swap through one
                  animation instead of flashing. A new activity in the
                  working title keeps its key, so it only resizes. */}
              <div className="flex-1 min-w-0">
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
                      processingDurationSeconds={
                        durationSeconds ?? timedSeconds
                      }
                      {...summary}
                    />
                  )}
                </Presence.Swap>
              </div>
              {foldable && (
                <>
                  {/* The timer is plain text beside the button: a button
                      label animates its changes, so each tick would flash. */}
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
                  {/* One fold button in every state, so its step count
                      animates as it changes. Its click reaches the row. */}
                  <Button
                    prominence="tertiary"
                    size="md"
                    rightIcon={isOpen ? SvgFold : SvgExpand}
                    aria-expanded={isOpen}
                  >
                    {t("stepsButton.label", { count: steps.length })}
                  </Button>
                </>
              )}
            </TimelineHeaderRow>
            {steps.map((step, index) => (
              <Fold key={step.id} open={isOpen}>
                {/* A step that streams in rises in, after the card opens room
                  for it. Steps already there when the card mounts (a saved
                  run) appear at once. */}
                <Presence appear={isRunning} grow>
                  {renderStep(step, {
                    isFirst: index === 0,
                    isLast: index === steps.length - 1,
                  })}
                </Presence>
              </Fold>
            ))}
          </Section>
        </RunCardSurface>
      </TimelineRoot>
    </Presence>
  );
}

export default RunCard;
