import React, { useCallback, useMemo } from "react";
import { SvgCircle } from "@opal/icons";

import {
  DeepResearchPlanPacket,
  PacketType,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
} from "@/app/app/message/messageComponents/interfaces";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import ExpandableTextDisplay from "@/refresh-components/texts/ExpandableTextDisplay";
import {
  mutedTextMarkdownComponents,
  collapsedMarkdownComponents,
} from "@/app/app/message/messageComponents/timeline/renderers/sharedMarkdownComponents";

/**
 * Renderer for deep research plan packets.
 * Streams the research plan content with a list icon.
 */
export const DeepResearchPlanRenderer: MessageRenderer<
  DeepResearchPlanPacket,
  FullChatState
> = ({ packets, stopPacketSeen, children }) => {
  const isComplete = packets.some((p) => p.obj.type === PacketType.SECTION_END);

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

  const statusText = isComplete ? "Generated plan" : "Generating plan";

  // Markdown renderer callback for ExpandableTextDisplay
  // Uses collapsed components (no spacing) in collapsed view, normal spacing in expanded modal
  const renderMarkdown = useCallback(
    (text: string, isExpanded: boolean) => (
      <MinimalMarkdown
        content={text}
        components={
          isExpanded ? mutedTextMarkdownComponents : collapsedMarkdownComponents
        }
      />
    ),
    []
  );

  const planContent = (
    <ExpandableTextDisplay
      title="Research Plan"
      content={fullContent}
      renderContent={renderMarkdown}
      isStreaming={!isComplete}
    />
  );

  return children([
    {
      icon: SvgCircle,
      status: statusText,
      content: planContent,
    },
  ]);
};
