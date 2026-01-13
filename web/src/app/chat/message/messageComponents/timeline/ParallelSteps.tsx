"use client";

import React from "react";
import Tabs from "@/refresh-components/Tabs";
import { FullChatState } from "../interfaces";
import { TurnGroup, TransformedStep } from "./transformers";
import { StepContent } from "./StepContent";

export interface ParallelStepsProps {
  /** Turn group containing parallel steps */
  turnGroup: TurnGroup;
  /** Chat state for rendering */
  chatState: FullChatState;
  /** Callback when a step completes */
  onStepComplete?: (step: TransformedStep) => void;
  /** Whether stop packet has been seen */
  stopPacketSeen?: boolean;
}

/**
 * ParallelSteps - Renders parallel tool executions as tabs
 *
 * When multiple tools execute in parallel (same turn_index, different tab_index),
 * they are displayed as tabs that can be switched between.
 *
 * Features:
 * - Uses existing Tabs component with loading indicator
 * - Each tab shows tool name and loading state
 * - Tab content renders using StepContent
 */
export function ParallelSteps({
  turnGroup,
  chatState,
  onStepComplete,
  stopPacketSeen = false,
}: ParallelStepsProps) {
  const { steps } = turnGroup;

  // If only one step, render directly without tabs
  if (steps.length === 1) {
    const step = steps[0];
    if (!step) return null;
    return (
      <StepContent
        packets={step.packets}
        chatState={chatState}
        isLoading={step.iconType === "loading"}
        onComplete={() => onStepComplete?.(step)}
        stopPacketSeen={stopPacketSeen}
      >
        {({ content }) => <>{content}</>}
      </StepContent>
    );
  }

  // Default to first tab
  const defaultValue = steps[0]?.tabIndex.toString() || "0";

  return (
    <Tabs defaultValue={defaultValue}>
      <Tabs.List>
        {steps.map((step) => (
          <Tabs.Trigger
            key={step.key}
            value={step.tabIndex.toString()}
            isLoading={step.iconType === "loading"}
          >
            {step.name}
          </Tabs.Trigger>
        ))}
      </Tabs.List>

      {steps.map((step) => (
        <Tabs.Content key={step.key} value={step.tabIndex.toString()}>
          <StepContent
            packets={step.packets}
            chatState={chatState}
            isLoading={step.iconType === "loading"}
            onComplete={() => onStepComplete?.(step)}
            stopPacketSeen={stopPacketSeen}
          >
            {({ content }) => content}
          </StepContent>
        </Tabs.Content>
      ))}
    </Tabs>
  );
}

export default ParallelSteps;
