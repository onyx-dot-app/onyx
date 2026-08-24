// Web sets the token CSS vars here; mobile bakes them as constants, so this is just the column + left gutter.
import type { ReactNode } from "react";
import { View } from "react-native";

import { timelineTokens } from "./timelineTokens";

export interface TimelineRootProps {
  children: ReactNode;
}

export function TimelineRoot({ children }: TimelineRootProps) {
  return (
    <View style={{ paddingLeft: timelineTokens.agentMessagePaddingLeft }}>
      {children}
    </View>
  );
}

export default TimelineRoot;
