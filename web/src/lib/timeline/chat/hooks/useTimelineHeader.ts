import { useMemo } from "react";
import { useLocale, useTranslations } from "next-intl";
import { TurnGroup } from "@/lib/timeline/chat/transformers";
import type { AwaitingUser } from "@/lib/chat/toolApprovals";
import {
  Packet,
  PacketType,
  SearchToolPacket,
  StopReason,
  CustomToolStart,
} from "@/app/app/services/streamingModels";
import {
  formatSearchHeader,
  constructCurrentSearchState,
} from "@/lib/timeline/chat/renderers/search/searchStateUtils";
import {
  firstActivityPacket,
  type TimelineTranslate,
} from "@/app/app/message/messageComponents/toolDisplayHelpers";

/** Header text for the activity of one step, or null for no tool activity. */
function stepHeaderText(
  packets: Packet[],
  t: TimelineTranslate,
  locale: string
): string | null {
  const firstPacket = firstActivityPacket(packets);
  if (!firstPacket) return null;

  switch (firstPacket.obj.type) {
    case PacketType.SEARCH_TOOL_START: {
      const searchState = constructCurrentSearchState(
        packets as SearchToolPacket[]
      );
      if (searchState.hasResults && !searchState.isInternetSearch) {
        return t("header.reading.label");
      }
      if (searchState.isInternetSearch) {
        return t("header.searchingWeb.label");
      }
      return formatSearchHeader(
        searchState.sourceFilters,
        searchState.timeFilter,
        t,
        locale
      );
    }
    case PacketType.FETCH_TOOL_START:
      return t("header.reading.label");
    case PacketType.PYTHON_TOOL_START:
      return t("header.executingCode.label");
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return t("header.generatingImages.label");
    case PacketType.FILE_READER_START:
      return t("header.readingFile.label");
    case PacketType.EXEC_COMMAND_START:
    case PacketType.WRITE_STDIN_START:
      return t("header.runningCommand.label");
    case PacketType.FILE_TOOL_PROGRESS:
    case PacketType.APPLY_PATCH_START:
      return t("header.editingFiles.label");
    case PacketType.PUBLISH_FILES_START:
      return t("header.publishingFiles.label");
    case PacketType.CUSTOM_TOOL_START: {
      const toolName = (firstPacket.obj as CustomToolStart).display_name;
      return toolName
        ? t("header.executingNamedTool.label", { toolName })
        : t("header.executingTool.label");
    }
    case PacketType.MEMORY_TOOL_START:
    case PacketType.MEMORY_TOOL_NO_ACCESS:
      return t("header.updatingMemory.label");
    case PacketType.POSTGRES_TOOL_START:
      return t("header.queryingKnowledgeBase.label");
    case PacketType.REASONING_START:
      return t("header.thinking.label");
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return t("header.generatingPlan.label");
    case PacketType.RESEARCH_AGENT_START:
      return t("header.researching.label");
    default:
      return null;
  }
}

export interface TimelineHeaderResult {
  headerText: string;
  hasPackets: boolean;
  userStopped: boolean;
}

/**
 * Hook that determines timeline header state based on current activity.
 * Returns header text, whether there are packets, and whether user stopped.
 */
export function useTimelineHeader(
  turnGroups: TurnGroup[],
  stopReason?: StopReason,
  codeModeWorking = false,
  awaitingUser: AwaitingUser | null = null
): TimelineHeaderResult {
  const t = useTranslations("chat.messages.timeline");
  const locale = useLocale();

  return useMemo(() => {
    const hasPackets = turnGroups.length > 0;
    const userStopped = stopReason === StopReason.USER_CANCELLED;
    if (awaitingUser) {
      return {
        headerText: t(
          awaitingUser === "approval"
            ? "header.waitingForApproval.label"
            : "header.waitingForAnswer.label"
        ),
        hasPackets,
        userStopped,
      };
    }

    const working = t("header.working.label");
    if (codeModeWorking) {
      return { headerText: working, hasPackets, userStopped };
    }

    // The current step's activity. A step with no activity of its own yet is
    // working.
    const packets = turnGroups.at(-1)?.steps[0]?.packets;
    const headerText =
      (packets && stepHeaderText(packets, t, locale)) ?? working;
    return { headerText, hasPackets, userStopped };
  }, [turnGroups, stopReason, codeModeWorking, awaitingUser, t, locale]);
}
