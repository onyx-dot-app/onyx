import { useMemo } from "react";
import {
  TurnGroup,
  TransformedStep,
} from "@/app/app/message/messageComponents/timeline/transformers";
import {
  isCodingAgentPackets,
  isResearchAgentPackets,
  stepSupportsCollapsedStreaming,
} from "@/app/app/message/messageComponents/timeline/packetHelpers";

export interface TimelineMetrics {
  totalSteps: number;
  isSingleStep: boolean;
  lastTurnGroup: TurnGroup | undefined;
  lastStep: TransformedStep | undefined;
  lastStepIsResearchAgent: boolean;
  lastStepSupportsCollapsedStreaming: boolean;
  containsCodingAgent: boolean;
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
    let containsCodingAgent = false;
    for (const tg of turnGroups) {
      totalSteps += tg.steps.length;
      if (!containsCodingAgent) {
        for (const step of tg.steps) {
          if (isCodingAgentPackets(step.packets)) {
            containsCodingAgent = true;
            break;
          }
        }
      }
    }

    const lastTurnGroup = turnGroups[turnGroups.length - 1];
    const lastStep = lastTurnGroup?.steps[lastTurnGroup.steps.length - 1];

    // Analyze last step packets once
    const lastStepIsResearchAgent = lastStep
      ? isResearchAgentPackets(lastStep.packets)
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
      lastStepSupportsCollapsedStreaming,
      containsCodingAgent,
    };
  }, [turnGroups, userStopped]);
}
