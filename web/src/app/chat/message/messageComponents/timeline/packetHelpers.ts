import { Packet, PacketType } from "@/app/chat/services/streamingModels";

// Packet types with renderers supporting compact mode
export const COMPACT_SUPPORTED_PACKET_TYPES = new Set<PacketType>([
  PacketType.SEARCH_TOOL_START,
  PacketType.FETCH_TOOL_START,
  PacketType.PYTHON_TOOL_START,
  PacketType.CUSTOM_TOOL_START,
]);

// Check if packets belong to a research agent (handles its own Done indicator)
export const isResearchAgentPackets = (packets: Packet[]): boolean =>
  packets.some((p) => p.obj.type === PacketType.RESEARCH_AGENT_START);

// Check if step supports compact rendering mode
export const stepSupportsCompact = (packets: Packet[]): boolean =>
  packets.some((p) =>
    COMPACT_SUPPORTED_PACKET_TYPES.has(p.obj.type as PacketType)
  );
