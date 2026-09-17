// Derived timeline metrics (step count + last-step flags). Pure port of web's useTimelineMetrics.

import { useMemo } from "react";

import {
  isCodingAgentItems,
  isResearchAgentItems,
  stepSupportsCollapsedStreaming,
} from "@/chat/timeline/itemHelpers";
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
      ? isResearchAgentItems(lastStep.items)
      : false;
    const lastStepIsCodingAgent = lastStep
      ? isCodingAgentItems(lastStep.items)
      : false;
    const lastStepSupportsCollapsedStreaming = lastStep
      ? stepSupportsCollapsedStreaming(lastStep.items)
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
