import { useMemo } from "react";
import {
  TurnGroup,
  TransformedStep,
} from "@/app/chat/message/messageComponents/timeline/transformers";
import {
  isResearchAgentPackets,
  stepSupportsCompact,
} from "@/app/chat/message/messageComponents/timeline/packetHelpers";

export interface TimelineMetrics {
  totalSteps: number;
  isSingleStep: boolean;
  lastTurnGroup: TurnGroup | undefined;
  lastStep: TransformedStep | undefined;
  lastStepIsResearchAgent: boolean;
  lastStepSupportsCompact: boolean;
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

    // Analyze last step packets once
    const lastStepIsResearchAgent = lastStep
      ? isResearchAgentPackets(lastStep.packets)
      : false;
    const lastStepSupportsCompact = lastStep
      ? stepSupportsCompact(lastStep.packets)
      : false;

    return {
      totalSteps,
      isSingleStep: totalSteps === 1 && !userStopped,
      lastTurnGroup,
      lastStep,
      lastStepIsResearchAgent,
      lastStepSupportsCompact,
    };
  }, [turnGroups, userStopped]);
}
