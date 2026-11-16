import React from "react";
import { cn } from "@opal/utils";

export interface TimelineHeaderRowProps {
  children?: React.ReactNode;
}

/** TimelineHeaderRow spans the run's card, above the rail and the steps. */
export function TimelineHeaderRow({ children }: TimelineHeaderRowProps) {
  return (
    <div className="flex w-full h-(--timeline-header-row-height)">
      {children}
    </div>
  );
}

export interface RunHeaderRowProps {
  /** The header folds the run, so it reacts to hover. */
  interactive: boolean;
  /** Tinted while the run works or is open. */
  tinted: boolean;
  /** Rounded at the bottom when no steps show below it. */
  roundedBottom: boolean;
  children?: React.ReactNode;
}

/** A run's header row: the header on the top of the run's card. */
export function RunHeaderRow({
  interactive,
  tinted,
  roundedBottom,
  children,
}: RunHeaderRowProps) {
  return (
    <TimelineHeaderRow>
      <div
        className={cn(
          "flex flex-1 min-w-0 h-full items-center justify-between p-(--spacing-inline-4) rounded-t-12 transition-colors duration-300",
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
