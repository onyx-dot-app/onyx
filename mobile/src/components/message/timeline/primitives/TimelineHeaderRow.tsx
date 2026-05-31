// TimelineHeaderRow.tsx — top header row (avatar slot + header content), aligned
// to the rail width. Ported from web TimelineHeaderRow.

import type { ReactNode } from "react";
import { View } from "react-native";

import { timelineTokens as T } from "@/theme/timelineTokens";

export interface TimelineHeaderRowProps {
  left?: ReactNode;
  children?: ReactNode;
}

export function TimelineHeaderRow({ left, children }: TimelineHeaderRowProps) {
  return (
    <View style={{ flexDirection: "row", width: "100%", height: T.headerRowHeight }}>
      <View
        style={{
          alignItems: "center",
          justifyContent: "center",
          width: T.railWidth,
          height: T.headerRowHeight,
        }}
      >
        {left}
      </View>
      <View style={{ flex: 1, minWidth: 0, height: "100%" }}>{children}</View>
    </View>
  );
}

export default TimelineHeaderRow;
