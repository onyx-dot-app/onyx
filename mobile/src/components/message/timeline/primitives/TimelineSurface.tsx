// TimelineSurface.tsx — background + rounded corners for a step. Ported from web
// TimelineSurface (tint -> background-tint-00, error -> status-error-00). Hover
// dropped. Returns null with no children.

import { Children, type ReactNode } from "react";
import { View, type ViewStyle } from "react-native";

import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import type { TimelineSurfaceBackground } from "@/components/message/interfaces";

export interface TimelineSurfaceProps {
  children: ReactNode;
  style?: ViewStyle;
  roundedTop?: boolean;
  roundedBottom?: boolean;
  background?: TimelineSurfaceBackground;
}

export function TimelineSurface({
  children,
  style,
  roundedTop = false,
  roundedBottom = false,
  background = "tint",
}: TimelineSurfaceProps) {
  const colors = useThemeColors();

  if (Children.count(children) === 0) {
    return null;
  }

  const backgroundColor =
    background === "tint"
      ? colors["background-tint-00"]
      : background === "error"
        ? colors["status-error-00"]
        : undefined;

  return (
    <View
      style={[
        { flex: 1, flexDirection: "column" },
        backgroundColor ? { backgroundColor } : null,
        roundedTop
          ? { borderTopLeftRadius: radii["12"], borderTopRightRadius: radii["12"] }
          : null,
        roundedBottom
          ? {
              borderBottomLeftRadius: radii["12"],
              borderBottomRightRadius: radii["12"],
            }
          : null,
        style,
      ]}
    >
      {children}
    </View>
  );
}

export default TimelineSurface;
