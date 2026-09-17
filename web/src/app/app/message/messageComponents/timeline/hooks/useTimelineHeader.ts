import { useMemo } from "react";
import { useLocale, useTranslations } from "next-intl";
import { TurnGroup } from "@/app/app/message/messageComponents/timeline/transformers";
import { StopReason } from "@/app/app/services/streamingModels";
import {
  formatSearchHeader,
  constructCurrentSearchState,
} from "@/app/app/message/messageComponents/timeline/renderers/search/searchStateUtils";
import { displayType, firstTool } from "@/app/app/services/responseItems";

export interface TimelineHeaderResult {
  headerText: string;
  hasPackets: boolean;
  userStopped: boolean;
}

/**
 * Hook that determines timeline header state based on current activity.
 * Returns header text, whether there are items, and whether user stopped.
 */
export function useTimelineHeader(
  turnGroups: TurnGroup[],
  stopReason?: StopReason,
  isGeneratingImage?: boolean
): TimelineHeaderResult {
  const t = useTranslations("chat.messages.timeline");
  const locale = useLocale();

  return useMemo(() => {
    const hasPackets = turnGroups.length > 0;
    const userStopped =
      stopReason === StopReason.USER_CANCELLED ||
      stopReason === StopReason.INTERRUPTED;
    const thinkingHeader = t("header.thinkingEllipsis.label");

    // If generating image with no tool items, show image generation header
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
    if (!currentStep?.items?.length) {
      return { headerText: thinkingHeader, hasPackets, userStopped };
    }

    const firstPacket = currentStep.items[0];
    if (!firstPacket) {
      return { headerText: thinkingHeader, hasPackets, userStopped };
    }

    const packetType = displayType(currentStep.items);

    // Determine header based on packet type
    if (packetType === "internal_search" || packetType === "web_search") {
      const searchState = constructCurrentSearchState(currentStep.items);
      let headerText: string;
      if (searchState.hasResults && !searchState.isInternetSearch) {
        headerText = t("header.reading.label");
      } else if (searchState.isInternetSearch) {
        headerText = t("header.searchingWeb.label");
      } else {
        headerText = formatSearchHeader(
          searchState.sourceFilters,
          searchState.timeFilter,
          t,
          locale
        );
      }
      return { headerText, hasPackets, userStopped };
    }

    if (packetType === "open_url") {
      return { headerText: t("header.reading.label"), hasPackets, userStopped };
    }

    if (packetType === "run_python") {
      return {
        headerText: t("header.executingCode.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === "generate_image") {
      return {
        headerText: t("header.generatingImages.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === "read_file") {
      return {
        headerText: t("header.readingFile.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === "custom") {
      const toolName = firstTool(currentStep.items)?.name ?? "";
      return {
        headerText: toolName
          ? t("header.executingNamedTool.label", { toolName })
          : t("header.executingTool.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === "add_memory") {
      return {
        headerText: t("header.updatingMemory.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === "reasoning") {
      return {
        headerText: t("header.thinking.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === "plan") {
      return {
        headerText: t("header.generatingPlan.label"),
        hasPackets,
        userStopped,
      };
    }

    if (packetType === "research_agent") {
      return {
        headerText: t("header.researching.label"),
        hasPackets,
        userStopped,
      };
    }

    return { headerText: thinkingHeader, hasPackets, userStopped };
  }, [turnGroups, stopReason, isGeneratingImage, t, locale]);
}
