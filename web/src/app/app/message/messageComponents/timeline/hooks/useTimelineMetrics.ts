import { useMemo } from "react";
import {
  TurnGroup,
  TransformedStep,
} from "@/app/app/message/messageComponents/timeline/transformers";
import {
  isCodingAgentItems,
  isResearchAgentItems,
  stepSupportsCollapsedStreaming,
} from "@/app/app/message/messageComponents/timeline/itemHelpers";

export interface TimelineMetrics {
  totalSteps: number;
  isSingleStep: boolean;
  lastTurnGroup: TurnGroup | undefined;
  lastStep: TransformedStep | undefined;
  lastStepIsResearchAgent: boolean;
  lastStepIsCodingAgent: boolean;
  lastStepSupportsCollapsedStreaming: boolean;
}

/**
 * Memoizes derived metrics from turn groups to avoid recomputation on every render.
 * Single-pass computation where possible for performance with large packet counts.
 */
export function useTimelineMetrics(
  turnGroups: TurnGroup[],
  userStopped: boolean
): TimelineMetrics {
  return useMemo(() => {
    // Compute in single pass
    let totalSteps = 0;
    for (const tg of turnGroups) {
      totalSteps += tg.steps.length;
    }

    const lastTurnGroup = turnGroups[turnGroups.length - 1];
    const lastStep = lastTurnGroup?.steps[lastTurnGroup.steps.length - 1];

    // Analyze last step items once
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
