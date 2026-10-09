// Rail-width cell (agent avatar) + header slot, so the header aligns with the step rail below it.
import type { ReactNode } from "react";
import { View } from "react-native";

import { timelineTokens } from "./timelineTokens";

export interface TimelineHeaderRowProps {
  left?: ReactNode;
  children?: ReactNode;
}

export function TimelineHeaderRow({ left, children }: TimelineHeaderRowProps) {
  return (
    <View
      className="w-full flex-row"
      style={{ height: timelineTokens.headerRowHeight }}
    >
      <View
        className="items-center justify-center"
        style={{
          width: timelineTokens.railWidth,
          height: timelineTokens.headerRowHeight,
        }}
      >
        {left}
      </View>
      <View className="h-full min-w-0 flex-1">{children}</View>
    </View>
  );
}

export default TimelineHeaderRow;
