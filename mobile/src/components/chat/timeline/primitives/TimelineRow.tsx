// Base row: rail column + content column. Hover props dropped.
import type { ReactNode } from "react";
import { View } from "react-native";

import {
  TimelineIconColumn,
  type TimelineRailVariant,
} from "./TimelineIconColumn";

// "none" omits the left column entirely (nested/parallel content).
export type TimelineRowRailVariant = TimelineRailVariant | "none";

export interface TimelineRowProps {
  railVariant?: TimelineRowRailVariant;
  icon?: ReactNode;
  showIcon?: boolean;
  // compact keeps rail alignment stable when the header is hidden.
  iconRowVariant?: "default" | "compact";
  isFirst?: boolean;
  isLast?: boolean;
  children?: ReactNode;
}

export function TimelineRow({
  railVariant = "rail",
  icon,
  showIcon = true,
  iconRowVariant = "default",
  isFirst = false,
  isLast = false,
  children,
}: TimelineRowProps) {
  return (
    <View className="w-full flex-row">
      {railVariant !== "none" && (
        <TimelineIconColumn
          variant={railVariant === "spacer" ? "spacer" : "rail"}
          icon={icon}
          showIcon={showIcon}
          iconRowVariant={iconRowVariant}
          isFirst={isFirst}
          isLast={isLast}
        />
      )}
      <View className="min-w-0 flex-1">{children}</View>
    </View>
  );
}

export default TimelineRow;
