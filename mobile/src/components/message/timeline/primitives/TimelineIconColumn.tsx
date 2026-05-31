// TimelineIconColumn.tsx — the left rail: vertical connector line + step icon.
//
// Ported from web TimelineIconColumn.tsx. Web draws the 1px line with `w-px`
// divs + `bg-border-*` and CSS-var heights; here we use Views with numeric
// tokens and a resolved border color. Hover states are dropped (no pointer on
// mobile). THREE paths: spacer (width only), default (top-connector + icon +
// filler), compact (single flex line, no icon — used for hidden-header steps).

import type { ReactNode } from "react";
import { View } from "react-native";

import { useToken } from "@/theme/ThemeProvider";
import { timelineTokens as T, TIMELINE_CONNECTOR_WIDTH } from "@/theme/timelineTokens";

export type TimelineRailVariant = "rail" | "spacer";

export interface TimelineIconColumnProps {
  variant?: TimelineRailVariant;
  isFirst?: boolean;
  isLast?: boolean;
  icon?: ReactNode;
  showIcon?: boolean;
  iconRowVariant?: "default" | "compact";
}

export function TimelineIconColumn({
  variant = "rail",
  isFirst = false,
  isLast = false,
  icon,
  showIcon = true,
  iconRowVariant = "default",
}: TimelineIconColumnProps) {
  const border = useToken("border-01");

  if (variant === "spacer") {
    return <View style={{ width: T.railWidth }} />;
  }

  const line = (extra?: object) => ({
    width: TIMELINE_CONNECTOR_WIDTH,
    backgroundColor: border,
    ...extra,
  });

  return (
    // No explicit height: in a flexDirection:row parent (TimelineRow) with the
    // default alignItems:'stretch', this column stretches to the row height so
    // the flex:1 segments below fill the remaining vertical space.
    <View style={{ width: T.railWidth, alignItems: "center" }}>
      <View
        style={{
          width: "100%",
          alignItems: "center",
          height:
            iconRowVariant === "compact"
              ? T.firstTopSpacerHeight
              : T.stepHeaderHeight,
        }}
      >
        {iconRowVariant === "default" ? (
          <>
            <View
              style={line({
                height: T.stepTopPadding * 2,
                backgroundColor: isFirst ? "transparent" : border,
              })}
            />
            <View
              style={{
                height: T.branchIconWrapperSize,
                width: T.branchIconWrapperSize,
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {showIcon ? icon : null}
            </View>
            <View style={line({ flex: 1 })} />
          </>
        ) : (
          <View
            style={line({
              flex: 1,
              backgroundColor: isFirst ? "transparent" : border,
            })}
          />
        )}
      </View>

      {!isLast && <View style={line({ flex: 1 })} />}
    </View>
  );
}

export default TimelineIconColumn;
