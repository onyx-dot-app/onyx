import { useMemo } from "react";
import { GroupedPacket } from "../packetProcessor";
import {
  transformPacketGroups,
  groupStepsByTurn,
  TurnGroup,
} from "./transformers";

export interface UseAgentTimelineResult {
  /** Turn groups for rendering (each turn may have parallel steps) */
  turnGroups: TurnGroup[];
  /** Whether there are any steps to render */
  hasSteps: boolean;
}

/**
 * Hook that transforms packet groups into timeline data.
 * Extracts the data transformation logic for use in AgentMessage.
 */
export function useAgentTimeline(
  packetGroups: GroupedPacket[]
): UseAgentTimelineResult {
  const allSteps = useMemo(
    () => transformPacketGroups(packetGroups),
    [packetGroups]
  );

  const turnGroups = useMemo(() => groupStepsByTurn(allSteps), [allSteps]);

  return {
    turnGroups,
    hasSteps: turnGroups.length > 0,
  };
}
