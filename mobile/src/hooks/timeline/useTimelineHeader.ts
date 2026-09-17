import { useMemo } from "react";

import { StopReason } from "@/chat/streamingModels";

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
    if (!currentStep?.items?.length) {
      return { headerText: "Thinking...", hasPackets, userStopped };
    }

    const content = currentStep.items[0]?.content;
    let headerText = "Thinking";
    if (content?.kind === "text" && content.purpose === "plan")
      headerText = "Generating plan";
    if (content?.kind === "tool") {
      switch (content.name) {
        case "internal_search":
        case "web_search":
          headerText = "Searching";
          break;
        case "open_url":
          headerText = "Reading";
          break;
        case "run_python":
        case "python":
          headerText = "Executing code";
          break;
        case "generate_image":
          headerText = "Generating images";
          break;
        case "read_file":
          headerText = "Reading file";
          break;
        case "add_memory":
          headerText = "Updating memory...";
          break;
        case "research_agent":
          headerText = "Researching";
          break;
        default:
          headerText = `Executing ${content.name}`;
      }
    }
    return { headerText, hasPackets, userStopped };
  }, [turnGroups, stopReason, isGeneratingImage]);
}
