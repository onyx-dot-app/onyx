import type { useTranslations } from "next-intl";
import {
  ApplyPatchStart,
  CustomToolStart,
  FileToolName,
  Packet,
  PacketType,
  SearchToolPacket,
} from "@/app/app/services/streamingModels";
import { constructCurrentSearchState } from "@/lib/timeline/chat/renderers/search/searchStateUtils";
import { isDisplayPacket, isToolPacket } from "@/app/app/services/packetUtils";
import { SvgXCircle } from "@opal/icons";

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

/**
 * The packet that names a step's activity. Debug and approval packets share
 * the step's placement but never name it.
 */
export function firstActivityPacket(packets: Packet[]): Packet | undefined {
  return packets.find(
    (packet) => isToolPacket(packet, false) || isDisplayPacket(packet)
  );
}

export type TimelineTranslate = ReturnType<
  typeof useTranslations<"chat.messages.timeline">
>;

const FILE_TOOL_TITLES = {
  apply_patch: "toolNames.applyPatch",
  edit: "toolNames.editFile",
  write: "toolNames.writeFile",
} as const satisfies Record<FileToolName, string>;

export function getToolName(packets: Packet[], t: TimelineTranslate): string {
  const firstPacket = firstActivityPacket(packets);
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
    case PacketType.EXEC_COMMAND_START:
    case PacketType.WRITE_STDIN_START:
      return t("toolNames.terminal");
    case PacketType.APPLY_PATCH_START:
      return t(
        FILE_TOOL_TITLES[(firstPacket.obj as ApplyPatchStart).tool_name]
      );
    case PacketType.PUBLISH_FILES_START:
      return t("toolNames.publishFiles");
    case PacketType.FETCH_TOOL_START:
      return t("toolNames.openUrls");
    case PacketType.CUSTOM_TOOL_START: {
      return (
        (firstPacket.obj as CustomToolStart).display_name ||
        t("toolNames.customTool")
      );
    }
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return t("toolNames.generateImage");
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return t("toolNames.generatePlan");
    case PacketType.RESEARCH_AGENT_START:
      return t("toolNames.researchAgent");
    case PacketType.REASONING_START:
      return t("toolNames.thinking");
    case PacketType.MEMORY_TOOL_START:
    case PacketType.MEMORY_TOOL_NO_ACCESS:
      return t("toolNames.memory");
    case PacketType.POSTGRES_TOOL_START:
      return t("toolNames.knowledgeBaseQuery");
    default:
      return t("toolNames.tool");
  }
}
