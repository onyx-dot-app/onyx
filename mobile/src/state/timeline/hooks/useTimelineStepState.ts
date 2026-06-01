import { useMemo } from "react";
import { MemoryToolPacket } from "@/lib/types";
import { TurnGroup } from "@/state/timeline/transformers";
import { constructCurrentMemoryState } from "@/state/timeline/memoryStateUtils";
import { isMemoryToolPackets } from "@/state/timeline/packetHelpers";

interface MemoryStepState {
  memoryText: string | null;
  memoryOperation: "add" | "update" | null;
  memoryId: number | null;
  memoryIndex: number | null;
  isMemoryOnly: boolean;
}

export function useTimelineStepState(turnGroups: TurnGroup[]): MemoryStepState {
  return useMemo(() => {
    let memoryText: string | null = null;
    let memoryOperation: "add" | "update" | null = null;
    let memoryId: number | null = null;
    let memoryIndex: number | null = null;
    let foundMemory = false;

    let totalSteps = 0;
    let allMemory = true;

    for (const tg of turnGroups) {
      for (const step of tg.steps) {
        totalSteps++;
        const isMem = isMemoryToolPackets(step.packets);

        if (!isMem) {
          allMemory = false;
        }

        if (!foundMemory && isMem) {
          foundMemory = true;
          const state = constructCurrentMemoryState(
            step.packets as unknown as MemoryToolPacket[]
          );
          memoryText = state.memoryText;
          memoryOperation = state.operation;
          memoryId = state.memoryId;
          memoryIndex = state.index;
        }
      }
    }

    return {
      memoryText,
      memoryOperation,
      memoryId,
      memoryIndex,
      isMemoryOnly: totalSteps > 0 && allMemory,
    };
  }, [turnGroups]);
}
