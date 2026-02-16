import { useMemo } from "react";
import { TurnGroup } from "../transformers";
import {
  PacketType,
  SearchToolPacket,
  StopReason,
  CustomToolStart,
} from "@/app/app/services/streamingModels";
import { constructCurrentSearchState } from "@/app/app/message/messageComponents/timeline/renderers/search/searchStateUtils";

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
  return useMemo(() => {
    const hasPackets = turnGroups.length > 0;
    const userStopped = stopReason === StopReason.USER_CANCELLED;

    // If generating image with no tool packets, show image generation header
    if (isGeneratingImage && !hasPackets) {
      return { headerText: "Generating image...", hasPackets, userStopped };
    }

    if (!hasPackets) {
      return { headerText: "Thinking...", hasPackets, userStopped };
    }

    // Get the last (current) turn group
    const currentTurn = turnGroups[turnGroups.length - 1];
    if (!currentTurn) {
      return { headerText: "Thinking...", hasPackets, userStopped };
    }

    const currentStep = currentTurn.steps[0];
    if (!currentStep?.packets?.length) {
      return { headerText: "Thinking...", hasPackets, userStopped };
    }

    const firstPacket = currentStep.packets[0];
    if (!firstPacket) {
      return { headerText: "Thinking...", hasPackets, userStopped };
    }

    const packetType = firstPacket.obj.type;

    // Determine header based on packet type
    if (packetType === PacketType.SEARCH_TOOL_START) {
      const searchState = constructCurrentSearchState(
        currentStep.packets as SearchToolPacket[]
      );
      let headerText: string;
      if (searchState.hasResults && !searchState.isInternetSearch) {
        headerText = "Reading";
      } else {
        headerText = searchState.isInternetSearch
          ? "Searching the web"
          : "Searching internal documents";
      }
      return { headerText, hasPackets, userStopped };
    }

    if (packetType === PacketType.FETCH_TOOL_START) {
      return { headerText: "Reading", hasPackets, userStopped };
    }

    if (packetType === PacketType.PYTHON_TOOL_START) {
      return { headerText: "Executing code", hasPackets, userStopped };
    }

    if (packetType === PacketType.IMAGE_GENERATION_TOOL_START) {
      return { headerText: "Generating images", hasPackets, userStopped };
    }

    if (packetType === PacketType.FILE_READER_START) {
      return { headerText: "Reading file", hasPackets, userStopped };
    }

    if (packetType === PacketType.CUSTOM_TOOL_START) {
      const toolName = (firstPacket.obj as CustomToolStart).tool_name;
      return {
        headerText: toolName ? `Executing ${toolName}` : "Executing tool",
        hasPackets,
        userStopped,
      };
    }

    if (
      packetType === PacketType.MEMORY_TOOL_START ||
      packetType === PacketType.MEMORY_TOOL_NO_ACCESS
    ) {
      return { headerText: "Updating memory...", hasPackets, userStopped };
    }

    if (packetType === PacketType.REASONING_START) {
      return { headerText: "Thinking", hasPackets, userStopped };
    }

    if (packetType === PacketType.DEEP_RESEARCH_PLAN_START) {
      return { headerText: "Generating plan", hasPackets, userStopped };
    }

    if (packetType === PacketType.RESEARCH_AGENT_START) {
      return { headerText: "Researching", hasPackets, userStopped };
    }

    return { headerText: "Thinking...", hasPackets, userStopped };
  }, [turnGroups, stopReason, isGeneratingImage]);
}
