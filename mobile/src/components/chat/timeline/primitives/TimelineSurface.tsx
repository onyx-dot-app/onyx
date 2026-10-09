// Tint/error background + rounded corners for a step body. Hover + `transition-colors` dropped (no
// touch hover; RN has no CSS transitions). `TimelineSurfaceBackground` reused from the contract.
import React, { type ReactNode } from "react";
import { View } from "react-native";

import type { TimelineSurfaceBackground } from "@/components/chat/renderers/timelineContract";
import { cn } from "@/lib/utils";

export type { TimelineSurfaceBackground };

export interface TimelineSurfaceProps {
  children: ReactNode;
  className?: string;
  roundedTop?: boolean;
  roundedBottom?: boolean;
  background?: TimelineSurfaceBackground;
}

export function TimelineSurface({
  children,
  className,
  roundedTop = false,
  roundedBottom = false,
  background = "tint",
}: TimelineSurfaceProps) {
  if (React.Children.count(children) === 0) {
    return null;
  }

  const baseBackground =
    background === "tint"
      ? "bg-background-tint-00"
      : background === "error"
        ? "bg-status-error-00"
        : "";

  return (
    <View
      className={cn(
        baseBackground,
        roundedTop && "rounded-t-12",
        roundedBottom && "rounded-b-12",
        className,
      )}
    >
      {children}
    </View>
  );
}

export default TimelineSurface;
