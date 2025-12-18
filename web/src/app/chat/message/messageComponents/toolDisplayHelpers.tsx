import { JSX } from "react";
import {
  FiCircle,
  FiCode,
  FiGlobe,
  FiImage,
  FiLink,
  FiSearch,
  FiTool,
} from "react-icons/fi";

import {
  Packet,
  PacketType,
  SearchToolPacket,
} from "@/app/chat/services/streamingModels";
import { constructCurrentSearchState } from "./renderers/SearchToolRendererV2";

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
    default:
      return <FiCircle className="w-3.5 h-3.5" />;
  }
}
