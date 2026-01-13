"use client";

import React, { JSX } from "react";
import { Packet, StopReason } from "@/app/chat/services/streamingModels";
import { FullChatState, RenderType, RendererResult } from "../interfaces";
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
  /** Use short renderer (highlight mode) */
  useShortRenderer?: boolean;
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
  useShortRenderer = false,
  children,
}: StepContentProps) {
  const Renderer = findRendererForPackets(packets);
  const renderType = useShortRenderer ? RenderType.HIGHLIGHT : RenderType.FULL;

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
      renderType={renderType}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
    >
      {children || defaultChildren}
    </Renderer>
  );
}

/**
 * Simplified StepContent that just renders content without wrapper
 */
export function StepContentSimple({
  packets,
  chatState,
  isLoading,
  onComplete = () => {},
  stopPacketSeen = false,
  stopReason,
}: Omit<StepContentProps, "children" | "animate" | "useShortRenderer">) {
  return (
    <StepContent
      packets={packets}
      chatState={chatState}
      isLoading={isLoading}
      onComplete={onComplete}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
    >
      {({ content }) => <>{content}</>}
    </StepContent>
  );
}

export default StepContent;
