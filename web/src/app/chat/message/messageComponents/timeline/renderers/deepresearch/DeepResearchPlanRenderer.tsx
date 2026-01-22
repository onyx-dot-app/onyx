import React, { useMemo, useCallback } from "react";
import { FiList } from "react-icons/fi";

import {
  DeepResearchPlanPacket,
  PacketType,
} from "@/app/chat/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
} from "@/app/chat/message/messageComponents/interfaces";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import { mutedTextMarkdownComponents } from "@/app/chat/message/messageComponents/timeline/renderers/sharedMarkdownComponents";

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

  // Get the full content from all packets
  const fullContent = useMemo(
    () =>
      packets
        .map((packet) => {
          if (packet.obj.type === PacketType.DEEP_RESEARCH_PLAN_DELTA) {
            return packet.obj.content;
          }
          return "";
        })
        .join(""),
    [packets]
  );

  // Markdown renderer callback for ExpandableTextDisplay
  const renderMarkdown = useCallback(
    (text: string) => (
      <MinimalMarkdown
        content={text}
        components={mutedTextMarkdownComponents}
      />
    ),
    []
  );

  const statusText = isComplete ? "Generated plan" : "Generating plan";

  const planContent = (
    <ExpandableTextDisplay
      title="Deep research plan"
      content={fullContent}
      maxLines={5}
      renderContent={renderMarkdown}
      isStreaming={!isComplete && !stopPacketSeen}
    />
  );

  return children({
    icon: FiList,
    status: statusText,
    content: planContent,
    expandedText: planContent,
  });
};
