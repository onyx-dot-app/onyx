"use client";

import React, { useState, useCallback, JSX } from "react";
import { Packet, StopReason } from "@/app/app/services/streamingModels";
import {
  FullChatState,
  RenderType,
  RendererResult,
  RendererOutput,
} from "../interfaces";
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
  /** Hover state from parent */
  isHover: boolean;
  /** Whether parent should wrap with StepContainer or render raw content */
  timelineLayout: "timeline" | "content";
}

// All renderers return an array of results
export type TimelineRendererOutput = TimelineRendererResult[];

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
  /** Hover state from parent component */
  isHover?: boolean;
  /** Override render type (if not set, derives from defaultExpanded) */
  renderTypeOverride?: RenderType;
  /** Children render function - receives extended result with collapse state (single or array) */
  children: (result: TimelineRendererOutput) => JSX.Element;
}

// Custom comparison function to prevent unnecessary re-renders
// Only re-render if meaningful changes occur
function arePropsEqual(
  prev: TimelineRendererComponentProps,
  next: TimelineRendererComponentProps
): boolean {
  return (
    prev.packets === next.packets &&
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.animate === next.animate &&
    prev.isLastStep === next.isLastStep &&
    prev.isHover === next.isHover &&
    prev.defaultExpanded === next.defaultExpanded &&
    prev.renderTypeOverride === next.renderTypeOverride
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
    isHover = false,
    renderTypeOverride,
    children,
  }: TimelineRendererComponentProps) {
    const [isExpanded, setIsExpanded] = useState(defaultExpanded);
    const handleToggle = useCallback(() => setIsExpanded((prev) => !prev), []);
    const RendererFn = findRenderer({ packets });
    const renderType =
      renderTypeOverride ?? (isExpanded ? RenderType.FULL : RenderType.COMPACT);

    if (!RendererFn) {
      return children([
        {
          icon: null,
          status: null,
          content: <></>,
          supportsCollapsible: false,
          timelineLayout: "timeline",
          isExpanded,
          onToggle: handleToggle,
          renderType,
          isLastStep: isLastStep ?? true,
          isHover,
        },
      ]);
    }

    // Helper to add timeline context to a result
    const enhanceResult = (result: RendererResult): TimelineRendererResult => ({
      ...result,
      isExpanded,
      onToggle: handleToggle,
      renderType,
      isLastStep: isLastStep ?? true,
      isHover,
      timelineLayout: result.timelineLayout ?? "timeline",
    });

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
        isHover={isHover}
      >
        {(rendererOutput: RendererOutput) =>
          children(rendererOutput.map((result) => enhanceResult(result)))
        }
      </RendererFn>
    );
  },
  arePropsEqual
);
