import React from "react";

export interface TimelineHeaderRowProps {
  left?: React.ReactNode;
  children?: React.ReactNode;
}

/**
 * TimelineHeaderRow aligns the top header (e.g., agent avatar + title row)
 * with the same rail width used by the timeline steps.
 */
export function TimelineHeaderRow({ left, children }: TimelineHeaderRowProps) {
  return (
    <div className="flex w-full h-[var(--timeline-header-row-height)]">
      <div className="flex items-center justify-center w-[var(--timeline-rail-width)] h-[var(--timeline-header-row-height)]">
        {left}
      </div>
      <div className="flex-1 min-w-0 h-full">{children}</div>
    </div>
  );
}

export default TimelineHeaderRow;
