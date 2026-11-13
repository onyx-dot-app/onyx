import React from "react";
import { cn } from "@opal/utils";

export interface TimelineHeaderRowProps {
  left?: React.ReactNode;
  children?: React.ReactNode;
}

/**
 * TimelineHeaderRow aligns the top header (e.g., agent avatar + title row)
 * with the same rail width used by the timeline steps. The header icon sits in
 * its own padding, so its box matches the header text's box, and both center
 * in the header row.
 */
export function TimelineHeaderRow({ left, children }: TimelineHeaderRowProps) {
  return (
    <div className="flex w-full h-(--timeline-header-row-height)">
      <div className="flex items-center justify-center w-(--timeline-rail-width) h-(--timeline-header-row-height)">
        {left && (
          <div className="flex box-content size-(--timeline-header-icon-size) p-(--timeline-header-icon-padding)">
            {left}
          </div>
        )}
      </div>
      <div className="flex-1 min-w-0 h-full">{children}</div>
    </div>
  );
}

export interface RunHeaderRowProps {
  /** The agent avatar, on a response's first run only. */
  left?: React.ReactNode;
  /** The header folds the run, so it reacts to hover. */
  interactive: boolean;
  /** Tinted while the run works or is open. */
  tinted: boolean;
  /** Rounded at the bottom when no steps show below it. */
  roundedBottom: boolean;
  children?: React.ReactNode;
}

/** A run's header row: the avatar slot, then the header on its surface. */
export function RunHeaderRow({
  left,
  interactive,
  tinted,
  roundedBottom,
  children,
}: RunHeaderRowProps) {
  return (
    <TimelineHeaderRow left={left}>
      <div
        className={cn(
          "flex flex-1 min-w-0 h-full items-center justify-between p-(--timeline-header-surface-padding) rounded-t-12 transition-colors duration-300",
          interactive && "hover:bg-background-tint-00",
          tinted && "bg-background-tint-00",
          roundedBottom && "rounded-b-12"
        )}
      >
        {children}
      </div>
    </TimelineHeaderRow>
  );
}

export default TimelineHeaderRow;
