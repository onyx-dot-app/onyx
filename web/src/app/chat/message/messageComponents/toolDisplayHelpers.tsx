import { JSX } from "react";
import {
  FiCircle,
  FiCode,
  FiGlobe,
  FiImage,
  FiLink,
  FiList,
  FiSearch,
  FiTool,
  FiUsers,
  FiXCircle,
} from "react-icons/fi";
import { BrainIcon } from "@/components/icons/icons";

import {
  Packet,
  PacketType,
  SearchToolPacket,
} from "@/app/chat/services/streamingModels";
import { constructCurrentSearchState } from "./renderers/SearchToolRenderer";

/**
 * Check if a packet group contains an ERROR packet (tool failed)
 */
export function hasToolError(packets: Packet[]): boolean {
  return packets.some((p) => p.obj.type === PacketType.ERROR);
}

/**
 * Check if a tool group is complete.
 * For research agents, we only look at parent-level SECTION_END packets (sub_turn_index is undefined/null),
 * not the SECTION_END packets from nested tools (which have sub_turn_index as a number).
 */
export function isToolComplete(packets: Packet[]): boolean {
  const firstPacket = packets[0];
  if (!firstPacket) return false;

  // For research agents, only parent-level SECTION_END indicates completion
  // Nested tools (search, fetch, etc.) within the research agent have sub_turn_index set
  if (firstPacket.obj.type === PacketType.RESEARCH_AGENT_START) {
    return packets.some(
      (p) =>
        (p.obj.type === PacketType.SECTION_END ||
          p.obj.type === PacketType.ERROR) &&
        (p.placement.sub_turn_index === undefined ||
          p.placement.sub_turn_index === null)
    );
  }

  // For other tools, any SECTION_END or ERROR indicates completion
  return packets.some(
    (p) =>
      p.obj.type === PacketType.SECTION_END || p.obj.type === PacketType.ERROR
  );
}

/**
 * Get an error icon for failed tools
 */
export function getToolErrorIcon(): JSX.Element {
  return <FiXCircle className="w-3.5 h-3.5 text-error" />;
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
      const searchState = constructCurrentSearchState(
        packets as SearchToolPacket[]
      );
      return searchState.isInternetSearch ? "Web Search" : "Internal Search";
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
    case PacketType.REASONING_START:
      return "Thinking";
    default:
      return "Tool";
  }
}

export function getToolIcon(packets: Packet[]): JSX.Element {
  const firstPacket = packets[0];
  if (!firstPacket) return <FiCircle className="w-3.5 h-3.5" />;

  switch (firstPacket.obj.type) {
    case PacketType.SEARCH_TOOL_START: {
      const searchState = constructCurrentSearchState(
        packets as SearchToolPacket[]
      );
      return searchState.isInternetSearch ? (
        <FiGlobe className="w-3.5 h-3.5" />
      ) : (
        <FiSearch className="w-3.5 h-3.5" />
      );
    }
    case PacketType.PYTHON_TOOL_START:
      return <FiCode className="w-3.5 h-3.5" />;
    case PacketType.FETCH_TOOL_START:
      return <FiLink className="w-3.5 h-3.5" />;
    case PacketType.CUSTOM_TOOL_START:
      return <FiTool className="w-3.5 h-3.5" />;
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return <FiImage className="w-3.5 h-3.5" />;
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return <FiList className="w-3.5 h-3.5" />;
    case PacketType.RESEARCH_AGENT_START:
      return <FiUsers className="w-3.5 h-3.5" />;
    case PacketType.REASONING_START:
      return <BrainIcon className="w-3.5 h-3.5" />;
    default:
      return <FiCircle className="w-3.5 h-3.5" />;
  }
}
