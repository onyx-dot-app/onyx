import {
  PacketType,
  MemoryToolPacket,
  MemoryToolDelta,
} from "@/app/app/services/streamingModels";

export interface MemoryState {
  hasStarted: boolean;
  noAccess: boolean;
  memoryText: string | null;
  operation: "add" | "update" | null;
  memoryId: number | null;
  index: number | null;
  isComplete: boolean;
}

/** Constructs the current memory state from memory tool packets. */
export function constructCurrentMemoryState(
  packets: MemoryToolPacket[]
): MemoryState {
  const startPacket = packets.find(
    (packet) => packet.obj.type === PacketType.MEMORY_TOOL_START
  );
  const noAccessPacket = packets.find(
    (packet) => packet.obj.type === PacketType.MEMORY_TOOL_NO_ACCESS
  );
  const deltaPacket = packets.find(
    (packet) => packet.obj.type === PacketType.MEMORY_TOOL_DELTA
  )?.obj as MemoryToolDelta | undefined;
  const sectionEnd = packets.find(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  );

  const hasStarted = Boolean(startPacket || noAccessPacket);
  const noAccess = Boolean(noAccessPacket);
  const memoryText = deltaPacket?.memory_text ?? null;
  const operation = deltaPacket?.operation ?? null;
  const memoryId = deltaPacket?.memory_id ?? null;
  const index = deltaPacket?.index ?? null;
  const isComplete = Boolean(sectionEnd);

  return {
    hasStarted,
    noAccess,
    memoryText,
    operation,
    memoryId,
    index,
    isComplete,
  };
}
