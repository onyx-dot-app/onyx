// TimelineTopSpacer.tsx — vertical spacer at the top of a step body.
// Native mirror of web TimelineTopSpacer.

import { View } from "react-native";

import { timelineTokens as T } from "@/theme/timelineTokens";

export type TimelineTopSpacerVariant = "default" | "first" | "none";

export interface TimelineTopSpacerProps {
  variant?: TimelineTopSpacerVariant;
}

export function TimelineTopSpacer({ variant = "default" }: TimelineTopSpacerProps) {
  if (variant === "none") return null;
  if (variant === "first") return <View style={{ height: T.firstTopSpacerHeight }} />;
  return <View style={{ height: T.topConnectorHeight }} />;
}

export default TimelineTopSpacer;
