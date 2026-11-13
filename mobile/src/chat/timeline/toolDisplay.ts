// Pure tool key/name/completion helpers. Port of web's toolDisplayHelpers (its JSX icon factory is
// deferred to toolIcons.ts).

import {
  CustomToolStart,
  Packet,
  PacketType,
  SearchToolStart,
} from "@/chat/streamingModels";
import { isGroupEndPacket } from "@/chat/timeline/packetHelpers";

export function hasToolError(packets: Packet[]): boolean {
  return packets.some((p) => p.obj.type === PacketType.ERROR);
}

// A group is complete once a parent-level SECTION_END or ERROR arrives. Nested calls end with
// their own SECTION_END and do not count.
export function isToolComplete(packets: Packet[]): boolean {
  return packets.some(isGroupEndPacket);
}

export function getToolKey(turn_index: number, tab_index: number): string {
  return `${turn_index}-${tab_index}`;
}

export function parseToolKey(key: string): {
  turn_index: number;
  tab_index: number;
} {
  const parts = key.split("-");
  return {
    turn_index: parseInt(parts[0] ?? "0", 10),
    tab_index: parseInt(parts[1] ?? "0", 10),
  };
}

// Label a custom or MCP tool call by its display name; older servers send only
// the tool name.
export function customToolLabel(start: CustomToolStart): string {
  return start.display_name || start.tool_name;
}

export function getToolName(packets: Packet[]): string {
  const firstPacket = packets[0];
  if (!firstPacket) return "Tool";

  switch (firstPacket.obj.type) {
    case PacketType.SEARCH_TOOL_START: {
      // internet-vs-internal comes off the start packet; the full search-state reducer lands with
      // the search phase.
      const isInternetSearch =
        (firstPacket.obj as SearchToolStart).is_internet_search ?? false;
      return isInternetSearch ? "Web Search" : "Internal Search";
    }
    case PacketType.PYTHON_TOOL_START:
      return "Code Interpreter";
    case PacketType.FETCH_TOOL_START:
      return "Open URLs";
    case PacketType.CUSTOM_TOOL_START:
      return (
        customToolLabel(firstPacket.obj as CustomToolStart) || "Custom Tool"
      );
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return "Generate Image";
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return "Generate plan";
    case PacketType.RESEARCH_AGENT_START:
      return "Research agent";
    case PacketType.CODING_AGENT_START:
      return "Coding agent";
    case PacketType.REASONING_START:
      return "Thinking";
    case PacketType.MEMORY_TOOL_START:
    case PacketType.MEMORY_TOOL_NO_ACCESS:
      return "Memory";
    default:
      return "Tool";
  }
}
