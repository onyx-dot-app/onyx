// TimelineRoot.tsx — outer container. Native mirror of web TimelineRoot.
// CSS vars dropped; tokens are imported numerically by descendants.

import type { ReactNode } from "react";
import { View } from "react-native";

import { timelineTokens as T } from "@/theme/timelineTokens";

export interface TimelineRootProps {
  children: ReactNode;
}

export function TimelineRoot({ children }: TimelineRootProps) {
  return (
    <View style={{ flexDirection: "column", paddingLeft: T.agentMessagePaddingLeft }}>
      {children}
    </View>
  );
}

export default TimelineRoot;
