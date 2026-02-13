import { Packet, PacketType } from "@/app/app/services/streamingModels";

// Packet types with renderers supporting collapsed streaming mode
export const COLLAPSED_STREAMING_PACKET_TYPES = new Set<PacketType>([
  PacketType.SEARCH_TOOL_START,
  PacketType.FETCH_TOOL_START,
  PacketType.PYTHON_TOOL_START,
  PacketType.CUSTOM_TOOL_START,
  PacketType.RESEARCH_AGENT_START,
  PacketType.REASONING_START,
  PacketType.DEEP_RESEARCH_PLAN_START,
]);

// Check if packets belong to a research agent (handles its own Done indicator)
export const isResearchAgentPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.RESEARCH_AGENT_START);

// Check if packets belong to a search tool
export const isSearchToolPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.SEARCH_TOOL_START);

// Check if packets belong to a python tool
export const isPythonToolPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.PYTHON_TOOL_START);

// Check if packets belong to reasoning
export const isReasoningPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.REASONING_START);

// Check if step supports collapsed streaming rendering mode
export const stepSupportsCollapsedStreaming = (packets: Packet[]): boolean =>
  packets.some((p) =>
    COLLAPSED_STREAMING_PACKET_TYPES.has(p.obj.type as PacketType)
  );

// Check if packets have content worth rendering in collapsed streaming mode.
// Avoids rendering empty containers when only START packets have arrived.
export const stepHasCollapsedStreamingContent = (
  packets: Packet[]
): boolean => {
  const packetTypes = new Set(
    packets.map((packet) => packet.obj.type as PacketType)
  );

  // Errors should render even if no deltas arrived
  if (packetTypes.has(PacketType.ERROR)) {
    return true;
  }

  // Search tools need actual query/doc deltas before showing content
  if (
    packetTypes.has(PacketType.SEARCH_TOOL_QUERIES_DELTA) ||
    packetTypes.has(PacketType.SEARCH_TOOL_DOCUMENTS_DELTA)
  ) {
    return true;
  }

  // Fetch tool shows a loading indicator once started
  if (
    packetTypes.has(PacketType.FETCH_TOOL_START) ||
    packetTypes.has(PacketType.FETCH_TOOL_URLS) ||
    packetTypes.has(PacketType.FETCH_TOOL_DOCUMENTS)
  ) {
    return true;
  }

  // Python tool renders code/output from the start packet onward
  if (
    packetTypes.has(PacketType.PYTHON_TOOL_START) ||
    packetTypes.has(PacketType.PYTHON_TOOL_DELTA)
  ) {
    return true;
  }

  // Custom tool shows running/completed state after start
  if (
    packetTypes.has(PacketType.CUSTOM_TOOL_START) ||
    packetTypes.has(PacketType.CUSTOM_TOOL_DELTA)
  ) {
    return true;
  }

  // Research agent has meaningful content from start (task) or report deltas
  if (
    packetTypes.has(PacketType.RESEARCH_AGENT_START) ||
    packetTypes.has(PacketType.INTERMEDIATE_REPORT_START) ||
    packetTypes.has(PacketType.INTERMEDIATE_REPORT_DELTA) ||
    packetTypes.has(PacketType.INTERMEDIATE_REPORT_CITED_DOCS)
  ) {
    return true;
  }

  // Reasoning content only appears in deltas
  if (packetTypes.has(PacketType.REASONING_DELTA)) {
    return true;
  }

  // Deep research plan content only appears in deltas
  if (packetTypes.has(PacketType.DEEP_RESEARCH_PLAN_DELTA)) {
    return true;
  }

  return false;
};

// Check if packets belong to a deep research plan
export const isDeepResearchPlanPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.DEEP_RESEARCH_PLAN_START);

// Check if packets belong to a memory tool
export const isMemoryToolPackets = (packets: Packet[]): boolean =>
  packets.some(
    (p) =>
      p.obj.type === PacketType.MEMORY_TOOL_START ||
      p.obj.type === PacketType.MEMORY_TOOL_NO_ACCESS
  );
