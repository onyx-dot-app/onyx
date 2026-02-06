import React from "react";
import { cn } from "@/lib/utils";

export interface TimelineHeaderRowProps {
  left?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  leftClassName?: string;
  contentClassName?: string;
}

/**
 * TimelineHeaderRow aligns the top header (e.g., agent avatar + title row)
 * with the same rail width used by the timeline steps.
 */
export function TimelineHeaderRow({
  left,
  children,
  className,
  leftClassName,
  contentClassName,
}: TimelineHeaderRowProps) {
  return (
    <div
      className={cn(
        "flex w-full h-[var(--timeline-header-row-height)]",
        className
      )}
    >
      <div
        className={cn(
          "flex items-center justify-center w-[var(--timeline-rail-width)] h-[var(--timeline-header-row-height)]",
          leftClassName
        )}
      >
        {left}
      </div>
      <div className={cn("flex-1 min-w-0 h-full", contentClassName)}>
        {children}
      </div>
    </div>
  );
}

export default TimelineHeaderRow;
