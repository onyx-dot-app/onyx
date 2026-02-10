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
  disableTopConnectorHover?: boolean;
  icon?: React.ReactNode;
  showIcon?: boolean;
  /**
   * Controls the vertical height of the icon row.
   * - default: uses step header height for normal rows.
   * - compact: uses first-step spacer height for hidden headers.
   */
  iconRowVariant?: "default" | "compact";
}

/**
 * TimelineIconColumn renders the left rail (connector + icon).
 * For default rows, icon alignment is tied to step text padding:
 * - icon wrapper stays fixed at 1.25rem
 * - remaining top/bottom header space is filled with connector segments
 */
export function TimelineIconColumn({
  variant = "rail",
  isFirst = false,
  isLast = false,
  isHover = false,
  disableTopConnectorHover = false,
  icon,
  showIcon = true,
  iconRowVariant = "default",
}: TimelineIconColumnProps) {
  if (variant === "spacer") {
    return <div className="w-[var(--timeline-rail-width)]" />;
  }

  const connectorColorClass = isHover ? "bg-border-04" : "bg-border-01";
  const topConnectorColorClass = disableTopConnectorHover
    ? "bg-border-01"
    : connectorColorClass;

  return (
    <div className="relative flex flex-col items-center w-[var(--timeline-rail-width)]">
      <div
        className={cn(
          "w-full shrink-0 flex flex-col items-center",
          iconRowVariant === "compact"
            ? "h-[var(--timeline-first-top-spacer-height)]"
            : "h-[var(--timeline-step-header-height)]"
        )}
      >
        {iconRowVariant === "default" ? (
          <>
            <div
              className={cn(
                "w-px h-[calc(var(--timeline-step-top-padding)*2)]",
                !isFirst && topConnectorColorClass
              )}
            />
            <div className="h-[var(--timeline-branch-icon-wrapper-size)] w-[var(--timeline-branch-icon-wrapper-size)] shrink-0 flex items-center justify-center">
              {showIcon && icon}
            </div>
            <div className={cn("w-px flex-1", connectorColorClass)} />
          </>
        ) : (
          <div className={cn("w-px flex-1", !isFirst && connectorColorClass)} />
        )}
      </div>

      {!isLast && <div className={cn("w-px flex-1", connectorColorClass)} />}
    </div>
  );
}

export default TimelineIconColumn;
