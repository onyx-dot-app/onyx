"use client";

import React, { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Presence } from "@opal/components";
import { Section } from "@opal/layouts";
import { StopReason } from "@/app/app/services/streamingModels";
import { FullChatState } from "@/app/app/message/messageComponents/types";
import {
  TurnGroup,
  TransformedStep,
  toChatTimelineEntry,
} from "@/lib/timeline/chat/transformers";
import { useTimelineHeader } from "@/lib/timeline/chat/hooks/useTimelineHeader";
import { useTimelineStepState } from "@/lib/timeline/chat/hooks/useTimelineStepState";
import { useStreamingStartTime } from "@/app/app/stores/useChatSessionStore";
import { RunCard } from "@/lib/timeline/components/RunCard";
import { ChatStep } from "@/lib/timeline/chat/ChatStep";
import type { TimelineEntryStatus } from "@/lib/timeline/types";
import type { AwaitingUser } from "@/lib/chat/toolApprovals";

/**
 * A run with at most this many steps shows each step as a hoisted run card
 * (one step each); a run with more is one collapsed run card. Change it here.
 */
export const MAX_HOISTED_STEPS = 5;

export interface AgentTimelineProps {
  /** Turn groups from usePacketProcessor */
  turnGroups: TurnGroup[];
  /** Chat state for rendering content */
  chatState: FullChatState;
  /** Whether the stop packet has been seen */
  stopPacketSeen?: boolean;
  /** Reason for stopping (if stopped) */
  stopReason?: StopReason;
  /** Whether final answer is coming (affects last connector) */
  finalAnswerComing?: boolean;
  /** Whether there is display content after timeline */
  hasDisplayContent?: boolean;
  /** Processing duration in seconds (for completed messages) */
  processingDurationSeconds?: number;
  /** Tool processing duration from backend (via MESSAGE_START packet) */
  toolProcessingDuration?: number;
  /** A code mode program works between tool calls; it has no step */
  codeModeWorking?: boolean;
  /** A tool call in the latest turn waits for the user's approval or
   * answers */
  awaitingUser?: AwaitingUser | null;
}

/**
 * Custom prop comparison for AgentTimeline memoization.
 * Prevents unnecessary re-renders when parent renders but props haven't meaningfully changed.
 */
function areAgentTimelinePropsEqual(
  prev: AgentTimelineProps,
  next: AgentTimelineProps
): boolean {
  return (
    prev.turnGroups === next.turnGroups &&
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.finalAnswerComing === next.finalAnswerComing &&
    prev.hasDisplayContent === next.hasDisplayContent &&
    prev.processingDurationSeconds === next.processingDurationSeconds &&
    prev.chatState === next.chatState &&
    prev.toolProcessingDuration === next.toolProcessingDuration &&
    prev.codeModeWorking === next.codeModeWorking &&
    prev.awaitingUser === next.awaitingUser
  );
}

interface ChatRunStep {
  id: string;
  status: TimelineEntryStatus;
  step: TransformedStep;
}

/**
 * A step's status for the run card. A step that never closed counts as done
 * once the stream ends, or as stopped when the user stopped it.
 */
function runStatus(
  step: TransformedStep,
  stopPacketSeen: boolean,
  userStopped: boolean
): TimelineEntryStatus {
  const status = toChatTimelineEntry(step).status;
  if (status !== "streaming" || !stopPacketSeen) return status;
  return userStopped ? "stopped" : "done";
}

/** One run of a chat response's steps, on the shared run card. */
export const AgentTimeline = React.memo(function AgentTimeline({
  turnGroups,
  chatState,
  stopPacketSeen = false,
  stopReason,
  hasDisplayContent = false,
  processingDurationSeconds,
  toolProcessingDuration,
  codeModeWorking = false,
  awaitingUser = null,
}: AgentTimelineProps) {
  const { headerText, userStopped } = useTimelineHeader(
    turnGroups,
    stopReason,
    codeModeWorking,
    awaitingUser
  );
  const { memoryText, memoryOperation, memoryId, memoryIndex } =
    useTimelineStepState(turnGroups);
  const streamingStartTime = useStreamingStartTime();
  const t = useTranslations("chat.messages.timeline");

  const steps = useMemo<ChatRunStep[]>(
    () =>
      turnGroups
        .flatMap((group) => group.steps)
        .map((step) => ({
          id: step.key,
          status: runStatus(step, stopPacketSeen, userStopped),
          step,
        })),
    [turnGroups, stopPacketSeen, userStopped]
  );
  // The run works until the stream ends or text follows it; a wait for an
  // approval or an answer keeps it working after text.
  const isActive =
    !stopPacketSeen && (!hasDisplayContent || awaitingUser !== null);

  // Hoisted: each step of a short run is its own run card, with the step's
  // title as its header. Once the run has more steps, they collapse into one
  // run card.
  if (steps.length > 0 && steps.length <= MAX_HOISTED_STEPS) {
    return (
      <Section alignItems="stretch" gap={3} height="auto">
        {steps.map((runStep) => (
          // A step that arrives while the run works rises in; a saved
          // run's steps appear at once.
          <Presence key={runStep.id} appear={isActive} grow>
            <ChatStep
              step={runStep.step}
              status={runStep.status}
              position={{ isFirst: true, isLast: true }}
              chatState={chatState}
              stopPacketSeen={stopPacketSeen}
              stopReason={stopReason}
              asCard
            />
          </Presence>
        ))}
      </Section>
    );
  }

  return (
    // Collapsed: the run's steps in one run card, summed up rather than titled
    // by its current step. A wait for the user still says so.
    <RunCard
      steps={steps}
      workingText={
        awaitingUser !== null ? headerText : t("header.doingWork.label")
      }
      doneText={t("header.didWork.label")}
      // A run that just passed the limit swaps its step cards for this
      // card at once, with no entry.
      appear={steps.length <= MAX_HOISTED_STEPS}
      isActive={isActive}
      isStopped={stopPacketSeen && userStopped}
      autoCollapse={hasDisplayContent}
      streamingStartTime={streamingStartTime}
      durationSeconds={toolProcessingDuration ?? processingDurationSeconds}
      summary={{
        memoryText,
        memoryOperation,
        memoryId,
        memoryIndex,
      }}
      // Each step renders as a hoisted step does, so a step looks the same
      // in a collapsed run card as on its own.
      renderStep={(runStep, position) => (
        <ChatStep
          step={runStep.step}
          status={runStep.status}
          position={position}
          chatState={chatState}
          stopPacketSeen={stopPacketSeen}
          stopReason={stopReason}
          asCard
        />
      )}
    />
  );
}, areAgentTimelinePropsEqual);

export default AgentTimeline;
