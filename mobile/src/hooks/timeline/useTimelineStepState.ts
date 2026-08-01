// Memory-only extraction for the timeline. Port of web's useTimelineStepState, DORMANT in 9b: only
// isMemoryOnly is derived (the shell uses it for collapse gating); the memory text/operation/id/index
// stay null until the memory renderer phase wires constructCurrentMemoryState (03 §8(g)).

import { useMemo } from "react";

import { isMemoryToolPackets } from "@/chat/timeline/packetHelpers";
import { TurnGroup } from "@/chat/timeline/transformers";

export interface MemoryStepState {
  memoryText: string | null;
  memoryOperation: "add" | "update" | null;
  memoryId: number | null;
  memoryIndex: number | null;
  isMemoryOnly: boolean;
}

export function useTimelineStepState(turnGroups: TurnGroup[]): MemoryStepState {
  return useMemo(() => {
    let totalSteps = 0;
    let allMemory = true;

    for (const tg of turnGroups) {
      for (const step of tg.steps) {
        totalSteps++;
        if (!isMemoryToolPackets(step.packets)) {
          allMemory = false;
        }
      }
    }

    return {
      memoryText: null,
      memoryOperation: null,
      memoryId: null,
      memoryIndex: null,
      isMemoryOnly: totalSteps > 0 && allMemory,
    };
  }, [turnGroups]);
}
