import { useMemo } from "react";
import { MemoryToolPacket } from "@/app/app/services/streamingModels";
import { TurnGroup } from "@/app/app/message/messageComponents/timeline/transformers";
import { constructCurrentMemoryState } from "@/app/app/message/messageComponents/timeline/renderers/memory/memoryStateUtils";
import { isMemoryToolPackets } from "@/app/app/message/messageComponents/timeline/packetHelpers";

interface MemoryStepState {
  memoryText: string | null;
  memoryOperation: "add" | "update" | null;
  memoryId: number | null;
  memoryIndex: number | null;
  isMemoryOnly: boolean;
}

/**
 * Extracts memory state from the first memory-tool step in turnGroups
 * and determines whether the timeline contains only memory steps.
 */
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
