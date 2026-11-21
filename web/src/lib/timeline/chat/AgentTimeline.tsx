"use client";

import React, { useMemo } from "react";
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
  /** Number of images generated */
  generatedImageCount?: number;
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
    prev.generatedImageCount === next.generatedImageCount &&
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
  generatedImageCount = 0,
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
  const { memoryText, memoryOperation, memoryId, memoryIndex, isMemoryOnly } =
    useTimelineStepState(turnGroups);
  const streamingStartTime = useStreamingStartTime();

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

  return (
    <RunCard
      steps={steps}
      workingText={headerText}
      isActive={isActive}
      isStopped={stopPacketSeen && userStopped}
      autoCollapse={hasDisplayContent}
      streamingStartTime={streamingStartTime}
      durationSeconds={toolProcessingDuration ?? processingDurationSeconds}
      summary={{
        generatedImageCount,
        isMemoryOnly,
        memoryText,
        memoryOperation,
        memoryId,
        memoryIndex,
      }}
      renderStep={(runStep, position) => (
        <ChatStep
          step={runStep.step}
          status={runStep.status}
          position={position}
          chatState={chatState}
          stopPacketSeen={stopPacketSeen}
          stopReason={stopReason}
        />
      )}
    />
  );
}, areAgentTimelinePropsEqual);

export default AgentTimeline;
