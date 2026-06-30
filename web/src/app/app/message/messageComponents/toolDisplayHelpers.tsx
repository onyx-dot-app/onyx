import { FiCircle, FiList, FiTool } from "react-icons/fi";
import {
  Packet,
  PacketType,
  SearchToolPacket,
} from "@/app/app/services/streamingModels";
import { constructCurrentSearchState } from "./timeline/renderers/search/searchStateUtils";
import i18n from "@/lib/i18n";
import {
  SvgGlobe,
  SvgSearchMenu,
  SvgTerminal,
  SvgLink,
  SvgImage,
  SvgUser,
  SvgCircle,
  SvgBookOpen,
  SvgSlowTime,
  SvgXCircle,
  SvgCode,
} from "@opal/icons";

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

  // For coding agents, the CodingAgentFinal packet (or an error) marks completion.
  // Nested BashTool packets are part of the same group and don't indicate the
  // agent is done.
  if (firstPacket.obj.type === PacketType.CODING_AGENT_START) {
    return packets.some(
      (p) =>
        p.obj.type === PacketType.CODING_AGENT_FINAL ||
        p.obj.type === PacketType.ERROR
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
export function getToolErrorIcon(): React.ReactNode {
  return <SvgXCircle className="w-3.5 h-3.5 text-error" />;
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
  if (!firstPacket) return i18n.t("chat.tool_display.tool");

  switch (firstPacket.obj.type) {
    case PacketType.SEARCH_TOOL_START: {
      const searchState = constructCurrentSearchState(
        packets as SearchToolPacket[]
      );
      return searchState.isInternetSearch
        ? i18n.t("admin.chat_preferences.tool_web_search")
        : i18n.t("admin.chat_preferences.tool_internal_search");
    }
    case PacketType.PYTHON_TOOL_START:
      return i18n.t("admin.chat_preferences.tool_code_interpreter");
    case PacketType.FETCH_TOOL_START:
      return i18n.t("admin.chat_preferences.tool_open_url");
    case PacketType.CUSTOM_TOOL_START:
      return (
        (firstPacket.obj as { tool_name?: string }).tool_name ||
        i18n.t("chat.tool_display.custom_tool")
      );
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return i18n.t("admin.chat_preferences.tool_image_gen");
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return i18n.t("chat.tool_display.generate_plan");
    case PacketType.RESEARCH_AGENT_START:
      return i18n.t("chat.tool_display.research_agent");
    case PacketType.CODING_AGENT_START:
      return i18n.t("admin.chat_preferences.tool_coding_agent");
    case PacketType.REASONING_START:
      return i18n.t("chat.tool_display.thinking");
    case PacketType.MEMORY_TOOL_START:
    case PacketType.MEMORY_TOOL_NO_ACCESS:
      return i18n.t("chat.tool_display.memory");
    default:
      return i18n.t("chat.tool_display.tool");
  }
}

export function getToolIcon(packets: Packet[]): React.ReactNode {
  const firstPacket = packets[0];
  if (!firstPacket) return <FiCircle className="w-3.5 h-3.5" />;

  switch (firstPacket.obj.type) {
    case PacketType.SEARCH_TOOL_START: {
      const searchState = constructCurrentSearchState(
        packets as SearchToolPacket[]
      );
      return searchState.isInternetSearch ? (
        <SvgGlobe className="w-3.5 h-3.5" />
      ) : (
        <SvgSearchMenu className="w-3.5 h-3.5" />
      );
    }
    case PacketType.PYTHON_TOOL_START:
      return <SvgTerminal className="w-3.5 h-3.5" />;
    case PacketType.FETCH_TOOL_START:
      return <SvgLink className="w-3.5 h-3.5" />;
    case PacketType.CUSTOM_TOOL_START:
      return <FiTool className="w-3.5 h-3.5" />;
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return <SvgImage className="w-3.5 h-3.5" />;
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return <FiList className="w-3.5 h-3.5" />;
    case PacketType.RESEARCH_AGENT_START:
      return <SvgUser className="w-3.5 h-3.5" />;
    case PacketType.CODING_AGENT_START:
      return <SvgCode className="w-3.5 h-3.5" />;
    case PacketType.REASONING_START:
      return <SvgSlowTime className="w-3.5 h-3.5" />;
    case PacketType.MEMORY_TOOL_START:
    case PacketType.MEMORY_TOOL_NO_ACCESS:
      return <SvgBookOpen className="w-3.5 h-3.5" />;
    default:
      return <SvgCircle className="w-3.5 h-3.5" />;
  }
}
