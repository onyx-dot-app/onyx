// TimelineRow.tsx — rail column + content column. Ported from web TimelineRow.

import type { ReactNode } from "react";
import { View } from "react-native";

import {
  TimelineIconColumn,
  type TimelineRailVariant,
} from "@/components/message/timeline/primitives/TimelineIconColumn";

export type TimelineRowRailVariant = TimelineRailVariant | "none";

export interface TimelineRowProps {
  railVariant?: TimelineRowRailVariant;
  icon?: ReactNode;
  showIcon?: boolean;
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
    // alignItems defaults to 'stretch', so the rail column (no fixed height)
    // stretches to the content column's height — required for the connector
    // flex:1 segments to fill.
    <View style={{ flexDirection: "row", width: "100%" }}>
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
      <View style={{ flex: 1, minWidth: 0 }}>{children}</View>
    </View>
  );
}

export default TimelineRow;
