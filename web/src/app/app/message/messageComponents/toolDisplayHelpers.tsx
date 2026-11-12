import type { useTranslations } from "next-intl";
import type { IconFunctionComponent } from "@opal/types";
import {
  CustomToolStart,
  Packet,
  PacketType,
  SearchToolPacket,
} from "@/app/app/services/streamingModels";
import { constructCurrentSearchState } from "@/app/app/message/messageComponents/timeline/renderers/search/searchStateUtils";
import { isGroupEndPacket } from "@/app/app/message/messageComponents/timeline/packetHelpers";
import {
  SvgListCheck,
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
  SvgWrench,
} from "@opal/icons";

/**
 * Check if a packet group contains an ERROR packet (tool failed)
 */
export function hasToolError(packets: Packet[]): boolean {
  return packets.some((p) => p.obj.type === PacketType.ERROR);
}

/**
 * Check if a tool group is complete: a parent-level SECTION_END or ERROR
 * arrived. Nested calls end with their own SECTION_END and do not count.
 */
export function isToolComplete(packets: Packet[]): boolean {
  return packets.some(isGroupEndPacket);
}

/**
 * Get an error icon for failed tools
 */
export function getToolErrorIcon(): React.ReactNode {
  return <SvgXCircle className="w-3.5 h-3.5 text-error" />;
}

export function getToolKey(turn_index: number, tab_index: number = 0): string {
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

// The model sees custom and MCP tools as `custom__<tool id>__<operation>` and
// `mcp__<server id>__<server name>__<tool>`. Users see the operation or tool name.
const QUALIFIED_EXTERNAL_TOOL_NAME =
  /^(?:custom__\d+|mcp__\d+__[A-Za-z0-9_-]*?)__(.+)$/;

export function externalToolLabel(toolName: string): string {
  return QUALIFIED_EXTERNAL_TOOL_NAME.exec(toolName)?.[1] ?? toolName;
}

export type TimelineTranslate = ReturnType<
  typeof useTranslations<"chat.messages.timeline">
>;

export function getToolName(packets: Packet[], t: TimelineTranslate): string {
  const firstPacket = packets[0];
  if (!firstPacket) return t("toolNames.tool");

  switch (firstPacket.obj.type) {
    case PacketType.SEARCH_TOOL_START: {
      const searchState = constructCurrentSearchState(
        packets as SearchToolPacket[]
      );
      return searchState.isInternetSearch
        ? t("toolNames.webSearch")
        : t("toolNames.internalSearch");
    }
    case PacketType.PYTHON_TOOL_START:
      return t("toolNames.codeInterpreter");
    case PacketType.FETCH_TOOL_START:
      return t("toolNames.openUrls");
    case PacketType.CUSTOM_TOOL_START: {
      const toolName = (firstPacket.obj as CustomToolStart).tool_name;
      return toolName ? externalToolLabel(toolName) : t("toolNames.customTool");
    }
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return t("toolNames.generateImage");
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return t("toolNames.generatePlan");
    case PacketType.RESEARCH_AGENT_START:
      return t("toolNames.researchAgent");
    case PacketType.CODING_AGENT_START:
      return t("toolNames.codingAgent");
    case PacketType.REASONING_START:
      return t("toolNames.thinking");
    case PacketType.MEMORY_TOOL_START:
    case PacketType.MEMORY_TOOL_NO_ACCESS:
      return t("toolNames.memory");
    default:
      return t("toolNames.tool");
  }
}

export function getToolIcon(packets: Packet[]): IconFunctionComponent {
  const firstPacket = packets[0];
  if (!firstPacket) return SvgCircle;

  switch (firstPacket.obj.type) {
    case PacketType.SEARCH_TOOL_START: {
      const searchState = constructCurrentSearchState(
        packets as SearchToolPacket[]
      );
      return searchState.isInternetSearch ? SvgGlobe : SvgSearchMenu;
    }
    case PacketType.PYTHON_TOOL_START:
      return SvgTerminal;
    case PacketType.FETCH_TOOL_START:
      return SvgLink;
    case PacketType.CUSTOM_TOOL_START:
      return SvgWrench;
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return SvgImage;
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return SvgListCheck;
    case PacketType.RESEARCH_AGENT_START:
      return SvgUser;
    case PacketType.CODING_AGENT_START:
      return SvgCode;
    case PacketType.REASONING_START:
      return SvgSlowTime;
    case PacketType.MEMORY_TOOL_START:
    case PacketType.MEMORY_TOOL_NO_ACCESS:
      return SvgBookOpen;
    default:
      return SvgCircle;
  }
}
