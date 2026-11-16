import React from "react";
import { cn } from "@opal/utils";

export interface TimelineHeaderRowProps {
  children?: React.ReactNode;
}

/**
 * A run's header row: the header text and its fold button. Its height comes
 * from them: the fold button is 28px.
 */
export function TimelineHeaderRow({ children }: TimelineHeaderRowProps) {
  return (
    <div className="flex w-full items-center justify-between">{children}</div>
  );
}

export interface RunCardSurfaceProps {
  /** The header folds the run, so the folded card reacts to hover. */
  interactive: boolean;
  /** Tinted while the run works or is open. */
  tinted: boolean;
  children?: React.ReactNode;
}

/**
 * The run card itself: one 0.25rem padding and one tint around the header and
 * the steps, so its rows add no padding of their own.
 */
export function RunCardSurface({
  interactive,
  tinted,
  children,
}: RunCardSurfaceProps) {
  return (
    <div
      className={cn(
        "rounded-12 p-(--spacing-inline-4) transition-colors duration-300",
        tinted && "bg-background-tint-00",
        interactive && !tinted && "hover:bg-background-tint-00"
      )}
    >
      {children}
    </div>
  );
}

export default TimelineHeaderRow;
