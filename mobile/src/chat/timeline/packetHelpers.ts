// Per-family packet predicates + collapsed-streaming sets. Port of web's packetHelpers.

import {
  CODE_INTERPRETER_TOOL_TYPES,
  CODE_MODE_TOOL_TYPE,
  Packet,
  PacketType,
  ToolCallArgumentDelta,
} from "@/chat/streamingModels";

// TOOL_CALL_ARGUMENT_DELTA is intentionally excluded — it needs a tool_type check (see
// stepSupportsCollapsedStreaming).
export const COLLAPSED_STREAMING_PACKET_TYPES = new Set<PacketType>([
  PacketType.SEARCH_TOOL_START,
  PacketType.FETCH_TOOL_START,
  PacketType.PYTHON_TOOL_START,
  PacketType.CUSTOM_TOOL_START,
  PacketType.RESEARCH_AGENT_START,
  PacketType.CODING_AGENT_START,
  PacketType.REASONING_START,
  PacketType.DEEP_RESEARCH_PLAN_START,
]);

// A packet from a tool call nested under a parent tool (code mode, research agent, coding agent).
// Nested packets share the parent's group key and set sub_turn_index.
export const isNestedPacket = (packet: Packet): boolean =>
  packet.placement.sub_turn_index != null;

// A parent-level SECTION_END or ERROR ends a group. A nested call ends with its own SECTION_END
// while the parent tool keeps running.
export const isGroupEndPacket = (packet: Packet): boolean =>
  !isNestedPacket(packet) &&
  (packet.obj.type === PacketType.SECTION_END ||
    packet.obj.type === PacketType.ERROR);

/** One nested tool call of a parent step, with its packets placed at parent level so it reads as
 * a standalone call. */
export interface NestedCall {
  subTurnIndex: number;
  packets: Packet[];
  complete: boolean;
}

/** Nested calls ordered by sub_turn_index, from packets already placed at parent level. */
export function nestedCallSnapshot(
  bySubTurn: ReadonlyMap<number, Packet[]>,
): NestedCall[] {
  return Array.from(bySubTurn.entries())
    .sort(([a], [b]) => a - b)
    .map(([subTurnIndex, callPackets]) => ({
      subTurnIndex,
      packets: [...callPackets],
      complete: callPackets.some(isGroupEndPacket),
    }));
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
  packet: Packet,
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

// The step-kind checks below take a step's own packets (GroupedPacket.packets), which exclude
// the packets of nested calls.
export const isResearchAgentPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.RESEARCH_AGENT_START);

// Parent-level packet types that identify a coding agent group. The agent's bash calls and
// thinking stream as nested sections of the same group.
export const CODING_AGENT_PACKET_TYPES = new Set<PacketType>([
  PacketType.CODING_AGENT_START,
  PacketType.CODING_AGENT_FINAL,
]);

export const isCodingAgentPackets = (packets: Packet[]): boolean =>
  packets.some((p) => CODING_AGENT_PACKET_TYPES.has(p.obj.type as PacketType));

// Parent-level packets that identify a code mode group: the streamed program (argument deltas),
// its start, and its output deltas.
export const isCodeModePacket = (packet: Packet): boolean =>
  !isNestedPacket(packet) &&
  (packet.obj.type === PacketType.CODE_MODE_START ||
    packet.obj.type === PacketType.CODE_MODE_DELTA ||
    (packet.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
      packet.obj.tool_type === CODE_MODE_TOOL_TYPE));

export const isSearchToolPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.SEARCH_TOOL_START);

export const isPythonToolPackets = (packets: Packet[]): boolean =>
  packets.some(
    (p) =>
      p.obj.type === PacketType.PYTHON_TOOL_START ||
      (p.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
        (p.obj as ToolCallArgumentDelta).tool_type ===
          CODE_INTERPRETER_TOOL_TYPES.PYTHON),
  );

export const isReasoningPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.REASONING_START);

export const stepSupportsCollapsedStreaming = (packets: Packet[]): boolean =>
  packets.some(
    (p) =>
      COLLAPSED_STREAMING_PACKET_TYPES.has(p.obj.type as PacketType) ||
      (p.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
        (p.obj as ToolCallArgumentDelta).tool_type ===
          CODE_INTERPRETER_TOOL_TYPES.PYTHON),
  );

// Whether a step has content worth rendering yet — avoids empty containers when only START packets
// have arrived.
export const stepHasCollapsedStreamingContent = (
  packets: Packet[],
): boolean => {
  const packetTypes = new Set(
    packets.map((packet) => packet.obj.type as PacketType),
  );

  if (packetTypes.has(PacketType.ERROR)) {
    return true;
  }

  if (
    packetTypes.has(PacketType.SEARCH_TOOL_QUERIES_DELTA) ||
    packetTypes.has(PacketType.SEARCH_TOOL_DOCUMENTS_DELTA)
  ) {
    return true;
  }

  if (
    packetTypes.has(PacketType.FETCH_TOOL_START) ||
    packetTypes.has(PacketType.FETCH_TOOL_URLS) ||
    packetTypes.has(PacketType.FETCH_TOOL_DOCUMENTS)
  ) {
    return true;
  }

  if (
    packetTypes.has(PacketType.PYTHON_TOOL_START) ||
    packetTypes.has(PacketType.PYTHON_TOOL_DELTA) ||
    packets.some(
      (p) =>
        p.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
        (p.obj as ToolCallArgumentDelta).tool_type ===
          CODE_INTERPRETER_TOOL_TYPES.PYTHON,
    )
  ) {
    return true;
  }

  if (
    packetTypes.has(PacketType.CUSTOM_TOOL_START) ||
    packetTypes.has(PacketType.CUSTOM_TOOL_DELTA)
  ) {
    return true;
  }

  if (
    packetTypes.has(PacketType.RESEARCH_AGENT_START) ||
    packetTypes.has(PacketType.INTERMEDIATE_REPORT_START) ||
    packetTypes.has(PacketType.INTERMEDIATE_REPORT_DELTA) ||
    packetTypes.has(PacketType.INTERMEDIATE_REPORT_CITED_DOCS)
  ) {
    return true;
  }

  if (isCodingAgentPackets(packets)) {
    return true;
  }

  if (packetTypes.has(PacketType.REASONING_DELTA)) {
    return true;
  }

  if (packetTypes.has(PacketType.DEEP_RESEARCH_PLAN_DELTA)) {
    return true;
  }

  return false;
};

export const isDeepResearchPlanPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.DEEP_RESEARCH_PLAN_START);

export const isMemoryToolPackets = (packets: Packet[]): boolean =>
  packets.some(
    (p) =>
      p.obj.type === PacketType.MEMORY_TOOL_START ||
      p.obj.type === PacketType.MEMORY_TOOL_NO_ACCESS,
  );
