import { useMemo } from "react";
import {
  TurnGroup,
  TransformedStep,
} from "@/app/app/message/messageComponents/timeline/transformers";
import { getToolIconByName } from "@/app/app/message/messageComponents/toolDisplayHelpers";
import {
  isResearchAgentPackets,
  stepSupportsCompact,
} from "@/app/app/message/messageComponents/timeline/packetHelpers";

export interface UniqueTool {
  key: string;
  name: string;
  icon: React.JSX.Element;
}

export interface TimelineMetrics {
  totalSteps: number;
  isSingleStep: boolean;
  uniqueTools: UniqueTool[];
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
  uniqueToolNames: string[],
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
      uniqueTools: uniqueToolNames.map((name) => ({
        key: name,
        name,
        icon: getToolIconByName(name),
      })),
      lastTurnGroup,
      lastStep,
      lastStepIsResearchAgent,
      lastStepSupportsCompact,
    };
  }, [turnGroups, uniqueToolNames, userStopped]);
}
