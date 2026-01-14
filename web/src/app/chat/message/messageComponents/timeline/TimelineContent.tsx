"use client";

import React from "react";
import { StopReason } from "@/app/chat/services/streamingModels";
import { FullChatState } from "../interfaces";
import { TurnGroup, TransformedStep } from "./transformers";
import { StepContainer, getFirstStep } from "./AgentTimeline";
import { StepContent } from "./StepContent";
import { ParallelSteps } from "./ParallelSteps";
import { cn } from "@/lib/utils";

export interface TimelineContentProps {
  /** Turn groups containing step data */
  turnGroups: TurnGroup[];
  /** Chat state for rendering */
  chatState: FullChatState;
  /** Whether stop packet has been seen */
  stopPacketSeen?: boolean;
  /** Reason for stopping */
  stopReason?: StopReason;
  /** Callback when a step completes */
  onStepComplete?: (step: TransformedStep) => void;
  /** Additional class names */
  className?: string;
}

/**
 * Renders the content column for the timeline.
 * Shows tool step content in containers, handling both single and parallel steps.
 */
export function TimelineContent({
  turnGroups,
  chatState,
  stopPacketSeen = false,
  stopReason,
  onStepComplete,
  className,
}: TimelineContentProps) {
  if (turnGroups.length === 0) return null;

  return (
    <StepContainer>
      {turnGroups.map((turnGroup) => {
        const firstStep = getFirstStep(turnGroup);
        if (!firstStep) return null;

        if (turnGroup.isParallel) {
          // Multiple steps in same turn - render as tabs
          return (
            <ParallelSteps
              key={`content-${turnGroup.turnIndex}`}
              turnGroup={turnGroup}
              chatState={chatState}
              stopPacketSeen={stopPacketSeen}
              onStepComplete={onStepComplete}
            />
          );
        }

        // Single steps in turn - render each
        return turnGroup.steps.map((step) => (
          <StepContent
            key={step.key}
            packets={step.packets}
            chatState={chatState}
            isLoading={step.iconType === "loading"}
            stopPacketSeen={stopPacketSeen}
            stopReason={stopReason}
            onComplete={() => onStepComplete?.(step)}
          >
            {({ content }) => <>{content}</>}
          </StepContent>
        ));
      })}
    </StepContainer>
  );
}
