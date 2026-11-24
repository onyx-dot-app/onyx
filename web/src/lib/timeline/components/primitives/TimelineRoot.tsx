import React from "react";
import {
  getTimelineStyles,
  TimelineTokens,
} from "@/lib/timeline/components/primitives/tokens";

export interface TimelineRootProps {
  children: React.ReactNode;
  tokens?: Partial<TimelineTokens>;
  ref?: React.Ref<HTMLDivElement>;
}

/**
 * TimelineRoot provides the shared sizing contract for all timeline primitives.
 * It sets CSS variables derived from TimelineTokens so rail width, header height,
 * and padding stay consistent across the timeline.
 */
export function TimelineRoot({ children, tokens, ref }: TimelineRootProps) {
  return (
    <div
      ref={ref}
      className="flex flex-col ps-(--timeline-agent-message-padding-left)"
      style={getTimelineStyles(tokens)}
    >
      {children}
    </div>
  );
}

export default TimelineRoot;
