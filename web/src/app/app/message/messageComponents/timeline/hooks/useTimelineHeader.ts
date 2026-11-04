import { useMemo } from "react";
import { useLocale, useTranslations } from "next-intl";
import { TurnGroup } from "@/app/app/message/messageComponents/timeline/transformers";
import { isDisplayPacket, isToolPacket } from "@/app/app/services/packetUtils";
import { isNestedPacket } from "@/app/app/message/messageComponents/timeline/packetHelpers";
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
} from "@/app/app/message/messageComponents/timeline/renderers/search/searchStateUtils";
import type { TimelineTranslate } from "@/app/app/message/messageComponents/toolDisplayHelpers";

/** Header text for the activity of one step, or null for no tool activity. */
function stepHeaderText(
  packets: Packet[],
  t: TimelineTranslate,
  locale: string
): string | null {
  // The step's own first packet decides the header; nested calls do not.
  const firstPacket = packets.find(
    (packet) =>
      !isNestedPacket(packet) &&
      (isToolPacket(packet, false) || isDisplayPacket(packet))
  );
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
    case PacketType.CUSTOM_TOOL_START: {
      const toolName = (firstPacket.obj as CustomToolStart).tool_name;
      return toolName
        ? t("header.executingNamedTool.label", { toolName })
        : t("header.executingTool.label");
    }
    case PacketType.MEMORY_TOOL_START:
    case PacketType.MEMORY_TOOL_NO_ACCESS:
      return t("header.updatingMemory.label");
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
  codeModeWorking = false
): TimelineHeaderResult {
  const t = useTranslations("chat.messages.timeline");
  const locale = useLocale();

  return useMemo(() => {
    const hasPackets = turnGroups.length > 0;
    const userStopped = stopReason === StopReason.USER_CANCELLED;
    const thinkingHeader = t("header.thinkingEllipsis.label");

    if (codeModeWorking) {
      return { headerText: t("header.working.label"), hasPackets, userStopped };
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

    const headerText =
      stepHeaderText(currentStep.packets, t, locale) ?? thinkingHeader;
    return { headerText, hasPackets, userStopped };
  }, [turnGroups, stopReason, codeModeWorking, t, locale]);
}
