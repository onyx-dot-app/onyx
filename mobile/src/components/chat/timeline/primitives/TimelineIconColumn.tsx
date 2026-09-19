// Left rail (connector + node icon). Hover dropped (no touch hover): connector rests at bg-border-01,
// node icon at text-02 (set by the caller).
import type { ReactNode } from "react";
import { View } from "react-native";

import { cn } from "@/lib/utils";

import { timelineTokens } from "./timelineTokens";

// spacer keeps the column width for alignment without drawing a rail.
export type TimelineRailVariant = "rail" | "spacer";

export interface TimelineIconColumnProps {
  variant?: TimelineRailVariant;
  isFirst?: boolean;
  isLast?: boolean;
  icon?: ReactNode;
  showIcon?: boolean;
  // compact = first-spacer height, for hidden headers; default = full step-header height.
  iconRowVariant?: "default" | "compact";
}

export function TimelineIconColumn({
  variant = "rail",
  isFirst = false,
  isLast = false,
  icon,
  showIcon = true,
  iconRowVariant = "default",
}: TimelineIconColumnProps) {
  if (variant === "spacer") {
    return <View style={{ width: timelineTokens.railWidth }} />;
  }

  return (
    <View
      className="relative items-center"
      style={{ width: timelineTokens.railWidth }}
    >
      <View
        className="w-full shrink-0 items-center"
        style={{
          height:
            iconRowVariant === "compact"
              ? timelineTokens.firstTopSpacerHeight
              : timelineTokens.stepHeaderHeight,
        }}
      >
        {iconRowVariant === "default" ? (
          <>
            <View
              className={cn("w-[1px]", !isFirst && "bg-border-01")}
              style={{ height: timelineTokens.stepTopPadding * 2 }}
            />
            <View
              className="shrink-0 items-center justify-center"
              style={{
                height: timelineTokens.branchIconWrapperSize,
                width: timelineTokens.branchIconWrapperSize,
              }}
            >
              {showIcon ? icon : null}
            </View>
            <View className="w-[1px] flex-1 bg-border-01" />
          </>
        ) : (
          <View className={cn("w-[1px] flex-1", !isFirst && "bg-border-01")} />
        )}
      </View>

      {!isLast && <View className="w-[1px] flex-1 bg-border-01" />}
    </View>
  );
}

export default TimelineIconColumn;
