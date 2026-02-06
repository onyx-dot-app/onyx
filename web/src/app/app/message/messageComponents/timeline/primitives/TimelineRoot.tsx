import React from "react";
import { cn } from "@/lib/utils";
import { getTimelineStyles, TimelineTokens } from "./tokens";

export interface TimelineRootProps {
  children: React.ReactNode;
  className?: string;
  tokens?: Partial<TimelineTokens>;
}

/**
 * TimelineRoot provides the shared sizing contract for all timeline primitives.
 * It sets CSS variables derived from TimelineTokens so rail width, header height,
 * and padding stay consistent across the timeline.
 */
export function TimelineRoot({
  children,
  className,
  tokens,
}: TimelineRootProps) {
  return (
    <div
      className={cn(
        "flex flex-col pl-[var(--timeline-agent-message-padding-left)]",
        className
      )}
      style={getTimelineStyles(tokens)}
    >
      {children}
    </div>
  );
}

export default TimelineRoot;
