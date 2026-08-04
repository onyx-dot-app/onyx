// Reserves the connector's height so a tabbed group's first row lines up with the sequential steps
// around it, which get that height from the connector itself.
import { View } from "react-native";

import { timelineTokens } from "./timelineTokens";

export type TimelineTopSpacerVariant = "default" | "first" | "none";

export interface TimelineTopSpacerProps {
  variant?: TimelineTopSpacerVariant;
}

export function TimelineTopSpacer({
  variant = "default",
}: TimelineTopSpacerProps) {
  if (variant === "none") {
    return null;
  }
  return (
    <View
      style={{
        height:
          variant === "first"
            ? timelineTokens.firstTopSpacerHeight
            : timelineTokens.topConnectorHeight,
      }}
    />
  );
}

export default TimelineTopSpacer;
