// Derived timeline metrics (step count + last-step flags). Pure port of web's useTimelineMetrics.

import { useMemo } from "react";

import {
  isCodingAgentPackets,
  isResearchAgentPackets,
  stepSupportsCollapsedStreaming,
} from "@/chat/timeline/packetHelpers";
import { TransformedStep, TurnGroup } from "@/chat/timeline/transformers";

export interface TimelineMetrics {
  totalSteps: number;
  isSingleStep: boolean;
  lastTurnGroup: TurnGroup | undefined;
  lastStep: TransformedStep | undefined;
  lastStepIsResearchAgent: boolean;
  lastStepIsCodingAgent: boolean;
  lastStepSupportsCollapsedStreaming: boolean;
}

export function useTimelineMetrics(
  turnGroups: TurnGroup[],
  userStopped: boolean,
): TimelineMetrics {
  return useMemo(() => {
    let totalSteps = 0;
    for (const tg of turnGroups) {
      totalSteps += tg.steps.length;
    }

    const lastTurnGroup = turnGroups[turnGroups.length - 1];
    const lastStep = lastTurnGroup?.steps[lastTurnGroup.steps.length - 1];

    const lastStepIsResearchAgent = lastStep
      ? isResearchAgentPackets(lastStep.packets)
      : false;
    const lastStepIsCodingAgent = lastStep
      ? isCodingAgentPackets(lastStep.packets)
      : false;
    const lastStepSupportsCollapsedStreaming = lastStep
      ? stepSupportsCollapsedStreaming(lastStep.packets)
      : false;

    return {
      totalSteps,
      isSingleStep: totalSteps === 1 && !userStopped,
      lastTurnGroup,
      lastStep,
      lastStepIsResearchAgent,
      lastStepIsCodingAgent,
      lastStepSupportsCollapsedStreaming,
    };
  }, [turnGroups, userStopped]);
}
