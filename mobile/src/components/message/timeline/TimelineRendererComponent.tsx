/* eslint-disable react-hooks/static-components -- findRenderer returns a STABLE
   module-level renderer fn; rendering it as <Renderer/> is intentional dynamic
   dispatch (each renderer keeps its own hook scope), not a render-time factory. */
// TimelineRendererComponent.tsx — bridges a step's packets to its renderer,
// owns per-step expand state, computes RenderType, and enhances results with
// timeline context. Native mirror of web TimelineRendererComponent.

import { memo, useCallback, useState, type ReactNode } from "react";

import type { Packet, StopReason } from "@/lib/types";
import {
  RenderType,
  type FullChatState,
  type RendererResult,
} from "@/components/message/interfaces";
import { findRenderer } from "@/components/message/renderMessageComponent";

export interface TimelineRendererResult extends RendererResult {
  isExpanded: boolean;
  onToggle: () => void;
  renderType: RenderType;
  isLastStep: boolean;
  timelineLayout: "timeline" | "content";
}

export type TimelineRendererOutput = TimelineRendererResult[];

export interface TimelineRendererComponentProps {
  packets: Packet[];
  chatState: FullChatState;
  animate: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  defaultExpanded?: boolean;
  isLastStep?: boolean;
  renderTypeOverride?: RenderType;
  children: (result: TimelineRendererOutput) => ReactNode;
}

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
    prev.defaultExpanded === next.defaultExpanded &&
    prev.renderTypeOverride === next.renderTypeOverride
    // chatState skipped (memoized upstream)
  );
}

export const TimelineRendererComponent = memo(function TimelineRendererComponent({
  packets,
  chatState,
  animate,
  stopPacketSeen,
  stopReason,
  defaultExpanded = true,
  isLastStep,
  renderTypeOverride,
  children,
}: TimelineRendererComponentProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const handleToggle = useCallback(() => setIsExpanded((p) => !p), []);
  const RendererFn = findRenderer(packets);
  const renderType =
    renderTypeOverride ?? (isExpanded ? RenderType.FULL : RenderType.COMPACT);

  const enhanceResult = (result: RendererResult): TimelineRendererResult => ({
    ...result,
    isExpanded,
    onToggle: handleToggle,
    renderType,
    isLastStep: isLastStep ?? true,
    timelineLayout: result.timelineLayout ?? "timeline",
  });

  if (!RendererFn) {
    return children([
      {
        icon: null,
        status: null,
        content: null,
        supportsCollapsible: false,
        timelineLayout: "timeline",
        isExpanded,
        onToggle: handleToggle,
        renderType,
        isLastStep: isLastStep ?? true,
      },
    ]);
  }

  // Render the renderer as a COMPONENT (JSX), not a direct function call, so its
  // hooks live in their own fiber — calling it as a function would fold its
  // hooks into this component and break the Rules of Hooks ("fewer hooks").
  const Renderer = RendererFn;
  return (
    <Renderer
      packets={packets}
      state={chatState}
      onComplete={NOOP}
      animate={animate}
      renderType={renderType}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
      isLastStep={isLastStep}
    >
      {(rendererOutput) =>
        children(rendererOutput.map((r) => enhanceResult(r)))
      }
    </Renderer>
  );
}, arePropsEqual);

function NOOP() {}

export default TimelineRendererComponent;
