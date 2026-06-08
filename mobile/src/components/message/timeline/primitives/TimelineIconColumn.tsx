// Native mirror of web TimelineIconColumn; web draws the 1px line with `w-px`
// divs, here Views with numeric tokens. Three variants: spacer (width only),
// default (top-connector + icon + filler), compact (single flex line, no icon).

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
    // No explicit height: stretches to the row height (parent alignItems
    // defaults to 'stretch') so the flex:1 segments below fill the rest.
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
