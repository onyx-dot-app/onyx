import React from "react";
import { cn } from "@/lib/utils";

/**
 * TimelineRailVariant controls whether a row shows the rail or only reserves width.
 * - rail: renders icon + connector line.
 * - spacer: keeps column width for alignment, but no rail.
 */
export type TimelineRailVariant = "rail" | "spacer";

export interface TimelineIconColumnProps {
  variant?: TimelineRailVariant;
  isFirst?: boolean;
  isLast?: boolean;
  isHover?: boolean;
  icon?: React.ReactNode;
  showIcon?: boolean;
  /**
   * Controls the vertical height of the icon row.
   * - default: uses step header height for normal rows.
   * - compact: uses first-step spacer height for hidden headers.
   */
  iconRowVariant?: "default" | "compact";
  className?: string;
}

/**
 * TimelineIconColumn renders the left rail (connector + icon).
 * The top connector is drawn outside layout flow so rows do not add spacing.
 */
export function TimelineIconColumn({
  variant = "rail",
  isFirst = false,
  isLast = false,
  isHover = false,
  icon,
  showIcon = true,
  iconRowVariant = "default",
  className,
}: TimelineIconColumnProps) {
  if (variant === "spacer") {
    return <div className={cn("w-[var(--timeline-rail-width)]", className)} />;
  }

  return (
    <div
      className={cn(
        "relative flex flex-col items-center w-[var(--timeline-rail-width)]",
        className
      )}
    >
      <div
        className={cn(
          "flex items-center justify-center shrink-0",
          iconRowVariant === "compact"
            ? "h-[var(--timeline-first-top-spacer-height)]"
            : "h-[var(--timeline-step-header-height)]"
        )}
      >
        {showIcon && icon}
      </div>

      {!isLast && (
        <div
          className={cn("w-px flex-1 bg-border-01", isHover && "bg-border-04")}
        />
      )}
    </div>
  );
}

export default TimelineIconColumn;
