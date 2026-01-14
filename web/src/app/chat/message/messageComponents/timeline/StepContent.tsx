"use client";

import React, { JSX } from "react";
import { Packet, StopReason } from "@/app/chat/services/streamingModels";
import { FullChatState, RendererResult, RenderType } from "../interfaces";
import { findRendererForPackets } from "./rendererRegistry";

export interface StepContentProps {
  /** Packets for this step */
  packets: Packet[];
  /** Chat state for rendering */
  chatState: FullChatState;
  /** Whether the step is loading */
  isLoading: boolean;
  /** Callback when rendering is complete */
  onComplete?: () => void;
  /** Whether animation is enabled */
  animate?: boolean;
  /** Whether stop packet has been seen */
  stopPacketSeen?: boolean;
  /** Reason for stopping */
  stopReason?: StopReason;
  /** Custom children render function */
  children?: (result: RendererResult) => JSX.Element;
}

/**
 * StepContent - Routes packets to the appropriate renderer
 *
 * Uses the renderer registry to find and invoke the correct renderer
 * for the given packets. Provides a simpler interface for timeline usage.
 */
export function StepContent({
  packets,
  chatState,
  isLoading,
  onComplete = () => {},
  animate = false,
  stopPacketSeen = false,
  stopReason,
  children,
}: StepContentProps) {
  const Renderer = findRendererForPackets(packets);

  if (!Renderer) {
    // No matching renderer - render empty
    const emptyResult: RendererResult = {
      icon: null,
      status: null,
      content: <></>,
    };
    return children ? <>{children(emptyResult)}</> : null;
  }

  // Default children render function - just render content
  const defaultChildren = (result: RendererResult): JSX.Element => (
    <div>{result.content}</div>
  );

  return (
    <Renderer
      packets={packets as any}
      state={chatState}
      onComplete={onComplete}
      animate={animate}
      renderType={RenderType.FULL}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
    >
      {children || defaultChildren}
    </Renderer>
  );
}

export default StepContent;
