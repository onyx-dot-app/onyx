import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { TurnGroup } from "../transformers";
import {
  PacketType,
  SearchToolPacket,
  StopReason,
  CustomToolStart,
} from "@/app/app/services/streamingModels";
import {
  formatSearchHeader,
  constructCurrentSearchState,
} from "@/app/app/message/messageComponents/timeline/renderers/search/searchStateUtils";

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
  isGeneratingImage?: boolean
): TimelineHeaderResult {
  const t = useTranslations("chat.messages.timeline");

  return useMemo(() => {
    const hasPackets = turnGroups.length > 0;
    const userStopped = stopReason === StopReason.USER_CANCELLED;
    const thinkingHeader = t("header.thinkingEllipsis.label");

    // If generating image with no tool packets, show image generation header
    if (isGeneratingImage && !hasPackets) {
      return {
        headerText: t("header.generatingImage.label"),
        hasPackets,
        userStopped,
      };
    }

    if (!hasPackets) {
      return { headerText: thinkingHeader, hasPackets, userStopped };
    }

    // Get the last (current) turn group
    const currentTurn = turnGroups[turnGroups.length - 1];
    if (!currentTurn) {
      return { headerText: thinkingHeader, hasPackets, userStopped };
    }

    const currentStep = currentTurn.steps[0];
    if (!currentStep?.packets?.length) {
      return { headerText: thinkingHeader, hasPackets, userStopped };
    }

    const firstPacket = currentStep.packets[0];
    if (!firstPacket) {
      return { headerText: thinkingHeader, hasPackets, userStopped };
    }

    const packetType = firstPacket.obj.type;

    // Determine header based on packet type
    if (packetType === PacketType.SEARCH_TOOL_START) {
      const searchState = constructCurrentSearchState(
        currentStep.packets as SearchToolPacket[]
      );
      let headerText: string;
      if (searchState.hasResults && !searchState.isInternetSearch) {
        headerText = t("header.reading.label");
      } else if (searchState.isInternetSearch) {
        headerText = t("header.searchingWeb.label");
      } else {
        headerText = formatSearchHeader(
          searchState.sourceFilters,
          searchState.timeFilter
        );
      }
      return { headerText, hasPackets, userStopped };
    }

    if (packetType === PacketType.FETCH_TOOL_START) {
      return { headerText: t("header.reading.label"), hasPackets, userStopped };
    }

    if (packetType === PacketType.PYTHON_TOOL_START) {
      return {
        headerText: t("header.executingCode.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === PacketType.IMAGE_GENERATION_TOOL_START) {
      return {
        headerText: t("header.generatingImages.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === PacketType.FILE_READER_START) {
      return {
        headerText: t("header.readingFile.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === PacketType.CUSTOM_TOOL_START) {
      const toolName = (firstPacket.obj as CustomToolStart).tool_name;
      return {
        headerText: toolName
          ? t("header.executingNamedTool.label", { toolName })
          : t("header.executingTool.label"),
        hasPackets,
        userStopped,
      };
    }

    if (
      packetType === PacketType.MEMORY_TOOL_START ||
      packetType === PacketType.MEMORY_TOOL_NO_ACCESS
    ) {
      return {
        headerText: t("header.updatingMemory.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === PacketType.REASONING_START) {
      return {
        headerText: t("header.thinking.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === PacketType.DEEP_RESEARCH_PLAN_START) {
      return {
        headerText: t("header.generatingPlan.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === PacketType.RESEARCH_AGENT_START) {
      return {
        headerText: t("header.researching.label"),
        hasPackets,
        userStopped,
      };
    }

    return { headerText: thinkingHeader, hasPackets, userStopped };
  }, [turnGroups, stopReason, isGeneratingImage, t]);
}
