// Pure tool key/name/completion helpers. Port of web's toolDisplayHelpers (its JSX icon factory is
// deferred to toolIcons.ts).

import { Packet, PacketType, SearchToolStart } from "@/chat/streamingModels";

export function hasToolError(packets: Packet[]): boolean {
  return packets.some((p) => p.obj.type === PacketType.ERROR);
}

// Research agents complete only on a parent-level SECTION_END (sub_turn_index null) — nested tool
// SECTION_ENDs don't count; coding agents on CodingAgentFinal/error; others on any SECTION_END/ERROR.
export function isToolComplete(packets: Packet[]): boolean {
  const firstPacket = packets[0];
  if (!firstPacket) return false;

  if (firstPacket.obj.type === PacketType.RESEARCH_AGENT_START) {
    return packets.some(
      (p) =>
        (p.obj.type === PacketType.SECTION_END ||
          p.obj.type === PacketType.ERROR) &&
        (p.placement.sub_turn_index === undefined ||
          p.placement.sub_turn_index === null),
    );
  }

  if (firstPacket.obj.type === PacketType.CODING_AGENT_START) {
    return packets.some(
      (p) =>
        p.obj.type === PacketType.CODING_AGENT_FINAL ||
        p.obj.type === PacketType.ERROR,
    );
  }

  return packets.some(
    (p) =>
      p.obj.type === PacketType.SECTION_END || p.obj.type === PacketType.ERROR,
  );
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
        (firstPacket.obj as { tool_name?: string }).tool_name || "Custom Tool"
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
