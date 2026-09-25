// Timeline header text derivation (packet-type → activity label). Port of web's useTimelineHeader.
// Search degrades to a generic "Searching" until the search phase ports constructCurrentSearchState
// (web's "Reading"/"Searching the web" sub-labels need it); every other branch is 1:1.

import { useMemo } from "react";

import {
  CustomToolStart,
  PacketType,
  StopReason,
} from "@/chat/streamingModels";
import { TurnGroup } from "@/chat/timeline/transformers";

export interface TimelineHeaderResult {
  headerText: string;
  hasPackets: boolean;
  userStopped: boolean;
}

export function useTimelineHeader(
  turnGroups: TurnGroup[],
  stopReason?: StopReason,
  isGeneratingImage?: boolean,
): TimelineHeaderResult {
  return useMemo(() => {
    const hasPackets = turnGroups.length > 0;
    const userStopped = stopReason === StopReason.USER_CANCELLED;

    if (isGeneratingImage && !hasPackets) {
      return { headerText: "Generating image...", hasPackets, userStopped };
    }

    if (!hasPackets) {
      return { headerText: "Thinking...", hasPackets, userStopped };
    }

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

    if (packetType === PacketType.SEARCH_TOOL_START) {
      // generic until the search phase (see file header)
      return { headerText: "Searching", hasPackets, userStopped };
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
