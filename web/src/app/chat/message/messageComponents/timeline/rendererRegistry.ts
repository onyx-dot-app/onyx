import { Packet, PacketType } from "@/app/chat/services/streamingModels";
import { MessageRenderer } from "../interfaces";
import { MessageTextRenderer } from "../renderers/MessageTextRenderer";
import { ImageToolRenderer } from "../renderers/ImageToolRenderer";
import { PythonToolRenderer } from "../renderers/PythonToolRenderer";
import { ReasoningRenderer } from "../renderers/ReasoningRenderer";
import CustomToolRenderer from "../renderers/CustomToolRenderer";
import { FetchToolRenderer } from "../renderers/FetchToolRenderer";
import { DeepResearchPlanRenderer } from "../renderers/DeepResearchPlanRenderer";
import { ResearchAgentRenderer } from "../renderers/ResearchAgentRenderer";
import { SearchToolRenderer } from "../renderers/SearchToolRenderer";

/**
 * Registry mapping packet types to their renderers
 * Extensible - add new entries for new tool types
 */
type RendererEntry = {
  /** Renderer component */
  renderer: MessageRenderer<any, any>;
  /** Predicate to check if this renderer handles the packets */
  matches: (packets: Packet[]) => boolean;
};

/**
 * Check if packets contain a specific packet type
 */
function hasPacketType(packets: Packet[], type: PacketType): boolean {
  return packets.some((p) => p.obj.type === type);
}

/**
 * Renderer registry - matchers are mutually exclusive
 */
const RENDERER_REGISTRY: RendererEntry[] = [
  // Chat messages
  {
    renderer: MessageTextRenderer,
    matches: (packets) =>
      hasPacketType(packets, PacketType.MESSAGE_START) ||
      hasPacketType(packets, PacketType.MESSAGE_DELTA),
  },

  // Deep research
  {
    renderer: DeepResearchPlanRenderer,
    matches: (packets) =>
      hasPacketType(packets, PacketType.DEEP_RESEARCH_PLAN_START),
  },
  {
    renderer: ResearchAgentRenderer,
    matches: (packets) =>
      hasPacketType(packets, PacketType.RESEARCH_AGENT_START) ||
      hasPacketType(packets, PacketType.INTERMEDIATE_REPORT_START),
  },

  // Standard tools
  {
    renderer: SearchToolRenderer,
    matches: (packets) => hasPacketType(packets, PacketType.SEARCH_TOOL_START),
  },
  {
    renderer: ImageToolRenderer,
    matches: (packets) =>
      hasPacketType(packets, PacketType.IMAGE_GENERATION_TOOL_START),
  },
  {
    renderer: PythonToolRenderer,
    matches: (packets) => hasPacketType(packets, PacketType.PYTHON_TOOL_START),
  },
  {
    renderer: CustomToolRenderer,
    matches: (packets) => hasPacketType(packets, PacketType.CUSTOM_TOOL_START),
  },
  {
    renderer: FetchToolRenderer,
    matches: (packets) => hasPacketType(packets, PacketType.FETCH_TOOL_START),
  },

  // Reasoning
  {
    renderer: ReasoningRenderer,
    matches: (packets) => hasPacketType(packets, PacketType.REASONING_START),
  },
];

/**
 * Find the appropriate renderer for a packet group
 * Returns null if no matching renderer found
 */
export function findRendererForPackets(
  packets: Packet[]
): MessageRenderer<any, any> | null {
  for (const entry of RENDERER_REGISTRY) {
    if (entry.matches(packets)) {
      return entry.renderer;
    }
  }
  return null;
}

/**
 * Register a new renderer (for extensibility)
 * Note: This mutates the registry - use with caution
 */
export function registerRenderer(entry: RendererEntry): void {
  RENDERER_REGISTRY.push(entry);
}

/**
 * Get all registered renderers (for debugging/testing)
 */
export function getRegisteredRenderers(): readonly RendererEntry[] {
  return RENDERER_REGISTRY;
}
