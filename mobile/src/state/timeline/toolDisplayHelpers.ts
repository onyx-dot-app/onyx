// toolDisplayHelpers.ts — tool-step presentation helpers (names, icon NAMES,
// completion/error detection, group-key parsing).
//
// Ported from web:
//   web/src/app/app/message/messageComponents/toolDisplayHelpers.tsx
// AMENDMENT (M5): getToolIcon returns an icon NAME (a string union), not a React
// component, so this module stays pure/leaf (no import edge into components/).
// A `components/message/timeline/toolIcon.tsx` helper maps the name → Svg*.

import { Packet, PacketType, SearchToolStart } from "@/lib/types";

/** Abstract icon name; mapped to a mobile Svg* component in the components layer. */
export type TimelineIconName =
  | "circle"
  | "search-menu"
  | "globe"
  | "terminal"
  | "external-link"
  | "image"
  | "book-open"
  | "user"
  | "sparkle"
  | "check-circle"
  | "x-circle"
  | "file-text"
  | "edit-big"
  | "branch"
  | "fold"
  | "expand"
  | "maximize-2"
  | "stop-circle"
  | "x-octagon";

/**
 * Whether a tool group is complete.
 * - Research agents: only PARENT-level SECTION_END (sub_turn_index null/undefined).
 * - Coding agents: CODING_AGENT_FINAL (or ERROR).
 * - Others: any SECTION_END / ERROR.
 */
export function isToolComplete(packets: Packet[]): boolean {
  const firstPacket = packets[0];
  if (!firstPacket) return false;

  if (firstPacket.obj.type === PacketType.RESEARCH_AGENT_START) {
    return packets.some(
      (p) =>
        (p.obj.type === PacketType.SECTION_END ||
          p.obj.type === PacketType.ERROR) &&
        (p.placement.sub_turn_index === undefined ||
          p.placement.sub_turn_index === null)
    );
  }

  if (firstPacket.obj.type === PacketType.CODING_AGENT_START) {
    return packets.some(
      (p) =>
        p.obj.type === PacketType.CODING_AGENT_FINAL ||
        p.obj.type === PacketType.ERROR
    );
  }

  return packets.some(
    (p) =>
      p.obj.type === PacketType.SECTION_END || p.obj.type === PacketType.ERROR
  );
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

function isInternetSearch(packets: Packet[]): boolean {
  return packets.some(
    (p) =>
      p.obj.type === PacketType.SEARCH_TOOL_START &&
      (p.obj as SearchToolStart).is_internet_search === true
  );
}

export function getToolName(packets: Packet[]): string {
  const firstPacket = packets[0];
  if (!firstPacket) return "Tool";

  switch (firstPacket.obj.type) {
    case PacketType.SEARCH_TOOL_START:
      return isInternetSearch(packets) ? "Web Search" : "Internal Search";
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

export function getToolIconName(packets: Packet[]): TimelineIconName {
  const firstPacket = packets[0];
  if (!firstPacket) return "circle";

  switch (firstPacket.obj.type) {
    case PacketType.SEARCH_TOOL_START:
      return isInternetSearch(packets) ? "globe" : "search-menu";
    case PacketType.PYTHON_TOOL_START:
      return "terminal";
    case PacketType.FETCH_TOOL_START:
      return "external-link";
    case PacketType.CUSTOM_TOOL_START:
      return "terminal";
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return "image";
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return "book-open";
    case PacketType.RESEARCH_AGENT_START:
      return "user";
    case PacketType.CODING_AGENT_START:
      return "terminal";
    case PacketType.REASONING_START:
      return "circle";
    case PacketType.MEMORY_TOOL_START:
    case PacketType.MEMORY_TOOL_NO_ACCESS:
      return "book-open";
    default:
      return "circle";
  }
}
