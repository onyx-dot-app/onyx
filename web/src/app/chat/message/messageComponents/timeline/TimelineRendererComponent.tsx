"use client";

import React, { useState, JSX } from "react";
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
  /** Whether this is the last step (passed through from props) */
  isLastStep: boolean;
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
  /** Whether this is the last step in the timeline (for connector line decisions) */
  isLastStep?: boolean;
  /** Children render function - receives extended result with collapse state */
  children: (result: TimelineRendererResult) => JSX.Element;
}

// Custom comparison function to prevent unnecessary re-renders
// Only re-render if meaningful changes occur
function arePropsEqual(
  prev: TimelineRendererComponentProps,
  next: TimelineRendererComponentProps
): boolean {
  return (
    prev.packets.length === next.packets.length &&
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.animate === next.animate &&
    prev.isLastStep === next.isLastStep &&
    prev.defaultExpanded === next.defaultExpanded
    // Skipping chatState (memoized upstream)
  );
}

export const TimelineRendererComponent = React.memo(
  function TimelineRendererComponent({
    packets,
    chatState,
    onComplete,
    animate,
    stopPacketSeen,
    stopReason,
    defaultExpanded = true,
    isLastStep,
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
        supportsCompact: false,
        isExpanded,
        onToggle: handleToggle,
        renderType,
        isLastStep: isLastStep ?? true,
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
        isLastStep={isLastStep}
      >
        {({ icon, status, content, expandedText, supportsCompact }) =>
          children({
            icon,
            status,
            content,
            expandedText,
            supportsCompact,
            isExpanded,
            onToggle: handleToggle,
            renderType,
            isLastStep: isLastStep ?? true,
          })
        }
      </RendererFn>
    );
  },
  arePropsEqual
);
