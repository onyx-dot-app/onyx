import React, { useMemo } from "react";
import { FiList } from "react-icons/fi";
import { SvgChevronDown } from "@opal/icons";
import { cn } from "@/lib/utils";

import {
  DeepResearchPlanPacket,
  PacketType,
} from "../../../services/streamingModels";
import { MessageRenderer, FullChatState } from "../interfaces";
import { usePacketAnimationAndCollapse } from "../hooks/usePacketAnimationAndCollapse";
import { useMarkdownRenderer } from "../markdownUtils";

/**
 * Renderer for deep research plan packets.
 * Streams the research plan content with a list icon.
 * Collapsible and auto-collapses when plan generation is complete.
 */
export const DeepResearchPlanRenderer: MessageRenderer<
  DeepResearchPlanPacket,
  FullChatState
> = ({
  packets,
  state,
  onComplete,
  renderType,
  animate,
  stopPacketSeen,
  children,
}) => {
  // Check if plan generation is complete (has SECTION_END)
  const isComplete = packets.some((p) => p.obj.type === PacketType.SECTION_END);

  // Use shared hook for animation and auto-collapse logic
  const { displayedPacketCount, isExpanded, toggleExpanded } =
    usePacketAnimationAndCollapse({
      packets,
      animate,
      isComplete,
      onComplete,
    });

  // Get the full content from all packets
  const fullContent = packets
    .map((packet) => {
      if (packet.obj.type === PacketType.DEEP_RESEARCH_PLAN_DELTA) {
        return packet.obj.content;
      }
      return "";
    })
    .join("");

  // Get content based on displayed packet count
  const content = useMemo(() => {
    if (!animate || displayedPacketCount === -1) {
      return fullContent;
    }

    return packets
      .slice(0, displayedPacketCount)
      .map((packet) => {
        if (packet.obj.type === PacketType.DEEP_RESEARCH_PLAN_DELTA) {
          return packet.obj.content;
        }
        return "";
      })
      .join("");
  }, [animate, displayedPacketCount, fullContent, packets]);

  // Use markdown renderer to render the plan content
  const { renderedContent } = useMarkdownRenderer(
    content,
    state,
    "text-text-03 font-main-ui-body"
  );

  const statusText = isComplete ? "Generated plan" : "Generating plan";

  const statusElement = (
    <div
      className="flex items-center justify-between gap-2 cursor-pointer group w-full"
      onClick={toggleExpanded}
    >
      <span>{statusText}</span>
      <div className="flex items-center gap-2">
        <SvgChevronDown
          className={cn(
            "w-4 h-4 stroke-text-400 transition-transform duration-150 ease-in-out",
            !isExpanded && "rotate-[-90deg]"
          )}
        />
      </div>
    </div>
  );

  const planContent = (
    <div className="text-text-600 text-sm overflow-hidden">
      {/* Collapsible content */}
      <div
        className={cn(
          "overflow-hidden transition-all duration-200 ease-in-out",
          isExpanded ? "max-h-[2000px] opacity-100 mt-2" : "max-h-0 opacity-0"
        )}
      >
        {renderedContent}
      </div>
    </div>
  );

  return children({
    icon: FiList,
    status: statusElement,
    content: planContent,
    expandedText: planContent,
  });
};
