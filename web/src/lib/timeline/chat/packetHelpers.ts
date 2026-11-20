import {
  CODE_MODE_TOOL_TYPE,
  isCodeInterpreterToolType,
  MemoryToolPacket,
  Packet,
  PacketType,
  ToolCallArgumentDelta,
} from "@/app/app/services/streamingModels";

// A packet from a tool call nested under a parent tool (code mode, research
// agent). Nested packets share the parent's group key and set sub_turn_index.
export const isNestedPacket = (packet: Packet): boolean =>
  packet.placement.sub_turn_index != null;

// A parent-level SECTION_END or ERROR ends a group. A nested call ends with its
// own SECTION_END while the parent tool keeps running.
export const isGroupEndPacket = (packet: Packet): boolean =>
  !isNestedPacket(packet) &&
  (packet.obj.type === PacketType.SECTION_END ||
    packet.obj.type === PacketType.ERROR);

/** One nested tool call of a parent step. */
export interface NestedCall {
  subTurnIndex: number;
  /** The call's packets placed at parent level (sub_turn_index null), so the
   * tool's own renderer and the step-kind checks read it as a standalone call. */
  packets: Packet[];
  complete: boolean;
}

/** Nested calls ordered by sub_turn_index, from packets already placed at
 * parent level. A call whose packet count did not change keeps its previous
 * object, and an unchanged list keeps its previous array, so memoized renderers
 * skip calls that have not changed. */
export function nestedCallSnapshot(
  bySubTurn: ReadonlyMap<number, Packet[]>,
  previous: NestedCall[] = []
): NestedCall[] {
  const previousByIndex = new Map(
    previous.map((call) => [call.subTurnIndex, call])
  );
  let changed = previous.length !== bySubTurn.size;
  const calls = Array.from(bySubTurn.entries())
    .sort(([a], [b]) => a - b)
    .map(([subTurnIndex, callPackets]): NestedCall => {
      const prior = previousByIndex.get(subTurnIndex);
      if (prior && prior.packets.length === callPackets.length) return prior;
      changed = true;
      return {
        subTurnIndex,
        packets: [...callPackets],
        complete: callPackets.some(isGroupEndPacket),
      };
    });
  return changed ? calls : previous;
}

/** What the parent-level packets of a code mode group say about its program. */
export interface CodeModeProgram {
  /** The cell the program runs in, once a start or output packet names it. */
  cellId: number | null;
  /** The program runs in this observation: it has started, and no final
   * delta has reported its status yet. A program that yields (status
   * "running") keeps running in its cell, but the model acts next; a later
   * wait_code observation shows it running again. */
  running: boolean;
}

/** The program after one more packet of its group. Call it only for code mode packets. */
export function nextCodeModeProgram(
  program: CodeModeProgram,
  packet: Packet
): CodeModeProgram {
  const obj = packet.obj;
  if (obj.type === PacketType.CODE_MODE_START) {
    return { cellId: program.cellId ?? obj.cell_id ?? null, running: true };
  }
  if (obj.type === PacketType.CODE_MODE_DELTA) {
    return {
      cellId: program.cellId ?? obj.cell_id ?? null,
      running: program.running && obj.status == null,
    };
  }
  return program;
}

// The step-kind checks below take a step's own packets (GroupedPacket.packets),
// which exclude the packets of nested calls.

// Parent-level packets that identify a code mode group: the streamed program
// (argument deltas), its start, and its output deltas.
export const isCodeModePacket = (packet: Packet): boolean =>
  !isNestedPacket(packet) &&
  (packet.obj.type === PacketType.CODE_MODE_START ||
    packet.obj.type === PacketType.CODE_MODE_DELTA ||
    (packet.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
      packet.obj.tool_type === CODE_MODE_TOOL_TYPE));

// Check if packets belong to a search tool
export const isSearchToolPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.SEARCH_TOOL_START);

// Check if packets belong to a python tool
export const isPythonToolPackets = (packets: Packet[]): boolean =>
  packets.some(
    (p) =>
      p.obj.type === PacketType.PYTHON_TOOL_START ||
      (p.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
        isCodeInterpreterToolType((p.obj as ToolCallArgumentDelta).tool_type))
  );

// Check if packets belong to a memory tool. A step holds the packets of one
// tool call, so a memory start/no-access packet identifies the whole step.
export const isMemoryToolPackets = (
  packets: Packet[]
): packets is MemoryToolPacket[] =>
  packets.some(
    (p) =>
      p.obj.type === PacketType.MEMORY_TOOL_START ||
      p.obj.type === PacketType.MEMORY_TOOL_NO_ACCESS
  );
