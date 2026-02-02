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

// Check if packets belong to reasoning
export const isReasoningPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.REASONING_START);

// Check if step supports collapsed streaming rendering mode
export const stepSupportsCollapsedStreaming = (packets: Packet[]): boolean =>
  packets.some((p) =>
    COLLAPSED_STREAMING_PACKET_TYPES.has(p.obj.type as PacketType)
  );
