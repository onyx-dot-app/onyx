// Owns one step's expand/collapse state, derives its RenderType, dispatches via `findRenderer`, and
// hands the enhanced results to `children`. Drops web's `isHover`; packets are already `Packet` at the
// dispatch boundary, so no `as any` is needed.
import { memo, useCallback, useState, type ReactElement } from "react";

import { findRenderer } from "@/components/chat/renderers/findRenderer";
import {
  RenderType,
  type FullChatState,
  type RendererOutput,
  type RendererResult,
  type TimelineRendererResult,
} from "@/components/chat/renderers/timelineContract";
import type { Packet, StopReason } from "@/chat/streamingModels";

export interface TimelineRendererComponentProps {
  packets: Packet[];
  chatState: FullChatState;
  animate: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  defaultExpanded?: boolean;
  isLastStep?: boolean;
  // Override the derived type (else FULL expanded / COMPACT collapsed).
  renderTypeOverride?: RenderType;
  children: (result: TimelineRendererResult[]) => ReactElement;
}

// Omits `children` and `chatState` by design (faithful to web): both take a fresh identity on every
// parent render, so comparing them would re-render on every stream tick and defeat the streaming perf
// isolation. Caller contract (wired in 9b.7): pass a stable (useCallback) `children` whose captured
// state is also surfaced through a compared prop below — otherwise that state can render stale.
function arePropsEqual(
  prev: TimelineRendererComponentProps,
  next: TimelineRendererComponentProps,
): boolean {
  return (
    prev.packets === next.packets &&
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.animate === next.animate &&
    prev.isLastStep === next.isLastStep &&
    prev.defaultExpanded === next.defaultExpanded &&
    prev.renderTypeOverride === next.renderTypeOverride
  );
}

export const TimelineRendererComponent = memo(
  function TimelineRendererComponent({
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
    const handleToggle = useCallback(() => setIsExpanded((prev) => !prev), []);
    const RendererFn = findRenderer(packets);
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
        },
      ]);
    }

    const enhanceResult = (result: RendererResult): TimelineRendererResult => ({
      ...result,
      isExpanded,
      onToggle: handleToggle,
      renderType,
      isLastStep: isLastStep ?? true,
      timelineLayout: result.timelineLayout ?? "timeline",
    });

    return (
      <RendererFn
        packets={packets}
        state={chatState}
        onComplete={() => {}}
        animate={animate}
        renderType={renderType}
        stopPacketSeen={stopPacketSeen}
        stopReason={stopReason}
        isLastStep={isLastStep}
      >
        {(rendererOutput: RendererOutput) =>
          children(rendererOutput.map(enhanceResult))
        }
      </RendererFn>
    );
  },
  arePropsEqual,
);

export default TimelineRendererComponent;
