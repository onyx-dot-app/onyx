import { useMemo } from "react";
import { TurnGroup } from "@/lib/timeline/chat/transformers";
import { constructCurrentMemoryState } from "@/lib/timeline/chat/renderers/memory/memoryStateUtils";
import { isMemoryToolPackets } from "@/lib/timeline/chat/packetHelpers";

interface MemoryStepState {
  memoryText: string | null;
  memoryOperation: "add" | "update" | null;
  memoryId: number | null;
  memoryIndex: number | null;
}

/** Extracts memory state from the first memory-tool step in turnGroups. */
export function useTimelineStepState(turnGroups: TurnGroup[]): MemoryStepState {
  return useMemo(() => {
    let memoryText: string | null = null;
    let memoryOperation: "add" | "update" | null = null;
    let memoryId: number | null = null;
    let memoryIndex: number | null = null;
    let foundMemory = false;

    for (const tg of turnGroups) {
      for (const step of tg.steps) {
        if (!isMemoryToolPackets(step.packets)) continue;

        if (!foundMemory) {
          foundMemory = true;
          const state = constructCurrentMemoryState(step.packets);
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
    };
  }, [turnGroups]);
}
