// Per-family packet predicates + collapsed-streaming sets. Port of web's packetHelpers.

import {
  CODE_INTERPRETER_TOOL_TYPES,
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

export const isResearchAgentPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.RESEARCH_AGENT_START);

// Bash packets are emitted into the coding-agent group, so any of these signals it.
export const CODING_AGENT_PACKET_TYPES = new Set<PacketType>([
  PacketType.CODING_AGENT_START,
  PacketType.CODING_AGENT_THINKING_DELTA,
  PacketType.CODING_AGENT_FINAL,
  PacketType.BASH_TOOL_START,
  PacketType.BASH_TOOL_DELTA,
]);

export const isCodingAgentPackets = (packets: Packet[]): boolean =>
  packets.some((p) => CODING_AGENT_PACKET_TYPES.has(p.obj.type as PacketType));

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
