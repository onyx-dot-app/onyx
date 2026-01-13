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
  /** Priority for matching (higher = checked first) */
  priority: number;
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
 * Renderer registry - ordered by priority
 */
const RENDERER_REGISTRY: RendererEntry[] = [
  // Chat messages
  {
    renderer: MessageTextRenderer,
    priority: 100,
    matches: (packets) =>
      hasPacketType(packets, PacketType.MESSAGE_START) ||
      hasPacketType(packets, PacketType.MESSAGE_DELTA),
  },

  // Deep research (high priority - may contain multiple packet types)
  {
    renderer: DeepResearchPlanRenderer,
    priority: 90,
    matches: (packets) =>
      hasPacketType(packets, PacketType.DEEP_RESEARCH_PLAN_START),
  },
  {
    renderer: ResearchAgentRenderer,
    priority: 85,
    matches: (packets) =>
      hasPacketType(packets, PacketType.RESEARCH_AGENT_START) ||
      hasPacketType(packets, PacketType.INTERMEDIATE_REPORT_START),
  },

  // Standard tools
  {
    renderer: SearchToolRenderer,
    priority: 50,
    matches: (packets) => hasPacketType(packets, PacketType.SEARCH_TOOL_START),
  },
  {
    renderer: ImageToolRenderer,
    priority: 50,
    matches: (packets) =>
      hasPacketType(packets, PacketType.IMAGE_GENERATION_TOOL_START),
  },
  {
    renderer: PythonToolRenderer,
    priority: 50,
    matches: (packets) => hasPacketType(packets, PacketType.PYTHON_TOOL_START),
  },
  {
    renderer: CustomToolRenderer,
    priority: 50,
    matches: (packets) => hasPacketType(packets, PacketType.CUSTOM_TOOL_START),
  },
  {
    renderer: FetchToolRenderer,
    priority: 50,
    matches: (packets) => hasPacketType(packets, PacketType.FETCH_TOOL_START),
  },

  // Reasoning (lower priority - fallback)
  {
    renderer: ReasoningRenderer,
    priority: 10,
    matches: (packets) => hasPacketType(packets, PacketType.REASONING_START),
  },
];

// Sort by priority (highest first) once at module load
const SORTED_REGISTRY = [...RENDERER_REGISTRY].sort(
  (a, b) => b.priority - a.priority
);

/**
 * Find the appropriate renderer for a packet group
 * Returns null if no matching renderer found
 */
export function findRendererForPackets(
  packets: Packet[]
): MessageRenderer<any, any> | null {
  for (const entry of SORTED_REGISTRY) {
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
  // Re-sort after adding
  SORTED_REGISTRY.length = 0;
  SORTED_REGISTRY.push(
    ...RENDERER_REGISTRY.sort((a, b) => b.priority - a.priority)
  );
}

/**
 * Get all registered renderers (for debugging/testing)
 */
export function getRegisteredRenderers(): readonly RendererEntry[] {
  return SORTED_REGISTRY;
}
