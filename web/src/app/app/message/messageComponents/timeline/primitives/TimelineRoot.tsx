import React from "react";
import { getTimelineStyles, TimelineTokens } from "./tokens";

export interface TimelineRootProps {
  children: React.ReactNode;
  tokens?: Partial<TimelineTokens>;
}

/**
 * TimelineRoot provides the shared sizing contract for all timeline primitives.
 * It sets CSS variables derived from TimelineTokens so rail width, header height,
 * and padding stay consistent across the timeline.
 */
export function TimelineRoot({ children, tokens }: TimelineRootProps) {
  return (
    <div
      className="flex flex-col pl-[var(--timeline-agent-message-padding-left)]"
      style={getTimelineStyles(tokens)}
    >
      {children}
    </div>
  );
}

export default TimelineRoot;
