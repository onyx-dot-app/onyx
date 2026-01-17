"use client";

import { useState, JSX } from "react";
import { Packet, StopReason } from "@/app/chat/services/streamingModels";
import { FullChatState, RenderType, RendererResult } from "../interfaces";
import { findRenderer } from "../renderMessageComponent";

/** Extended result that includes collapse state */
export interface TimelineRendererResult extends RendererResult {
  /** Current expanded state */
  isExpanded: boolean;
  /** Toggle callback */
  onToggle: () => void;
  /** Current render type */
  renderType: RenderType;
}

export interface TimelineRendererComponentProps {
  /** Packets to render */
  packets: Packet[];
  /** Chat state for rendering */
  chatState: FullChatState;
  /** Completion callback */
  onComplete: () => void;
  /** Whether to animate streaming */
  animate: boolean;
  /** Whether stop packet has been seen */
  stopPacketSeen: boolean;
  /** Reason for stopping */
  stopReason?: StopReason;
  /** Initial expanded state */
  defaultExpanded?: boolean;
  /** Children render function - receives extended result with collapse state */
  children: (result: TimelineRendererResult) => JSX.Element;
}

export function TimelineRendererComponent({
  packets,
  chatState,
  onComplete,
  animate,
  stopPacketSeen,
  stopReason,
  defaultExpanded = true,
  children,
}: TimelineRendererComponentProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const handleToggle = () => setIsExpanded((prev) => !prev);
  const RendererFn = findRenderer({ packets });
  const renderType = isExpanded ? RenderType.FULL : RenderType.COMPACT;

  if (!RendererFn) {
    return children({
      icon: null,
      status: null,
      content: <></>,
      isExpanded,
      onToggle: handleToggle,
      renderType,
    });
  }

  return (
    <RendererFn
      packets={packets as any}
      state={chatState}
      onComplete={onComplete}
      animate={animate}
      renderType={renderType}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
    >
      {({ icon, status, content, expandedText }) =>
        children({
          icon,
          status,
          content,
          expandedText,
          isExpanded,
          onToggle: handleToggle,
          renderType,
        })
      }
    </RendererFn>
  );
}
