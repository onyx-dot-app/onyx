import { ResponseItem } from "@/app/app/services/streamingModels";
import {
  isComplete as itemsComplete,
  toolMetadata,
} from "@/app/app/services/responseItems";

export interface MemoryState {
  hasStarted: boolean;
  noAccess: boolean;
  memoryText: string | null;
  operation: "add" | "update" | null;
  memoryId: number | null;
  index: number | null;
  isComplete: boolean;
}

export function constructCurrentMemoryState(
  items: ResponseItem[]
): MemoryState {
  const value = toolMetadata(items, "memory_result").at(-1);
  return {
    hasStarted: items.length > 0,
    noAccess: items.some((item) => item.content.status === "error"),
    memoryText: value?.memory_text ?? null,
    operation: value?.operation ?? null,
    memoryId: value?.memory_id ?? null,
    index: value?.index ?? null,
    isComplete: itemsComplete(items),
  };
}
