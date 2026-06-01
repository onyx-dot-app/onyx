// TimelineStepContent.tsx — step header (status + fold/expand) + body.
// Native mirror of web TimelineStepContent. Web Button -> Pressable + icon; status
// rendered via Opal Text when it's a string, else the node is rendered directly
// (RN can't nest arbitrary Views inside <Text>).

import { type ReactNode } from "react";
import { View, Pressable } from "react-native";

import { Text } from "@/components/opal";
import { useToken } from "@/theme/ThemeProvider";
import { timelineTokens as T } from "@/theme/timelineTokens";
import {
  SvgFold,
  SvgExpand,
  SvgXOctagon,
} from "@/components/icons";
import type { TimelineSurfaceBackground } from "@/components/message/interfaces";

export interface TimelineStepContentProps {
  children?: ReactNode;
  header?: ReactNode;
  isExpanded?: boolean;
  onToggle?: () => void;
  collapsible?: boolean;
  supportsCollapsible?: boolean;
  hideHeader?: boolean;
  noPaddingRight?: boolean;
  surfaceBackground?: TimelineSurfaceBackground;
}

export function TimelineStepContent({
  children,
  header,
  isExpanded = true,
  onToggle,
  collapsible = true,
  supportsCollapsible = false,
  hideHeader = false,
  noPaddingRight = false,
  surfaceBackground,
}: TimelineStepContentProps) {
  const errorColor = useToken("status-error-05");
  const showCollapseControls = collapsible && supportsCollapsible && !!onToggle;
  const ToggleIcon = isExpanded ? SvgFold : SvgExpand;

  return (
    <View style={{ flexDirection: "column", paddingHorizontal: 4, paddingBottom: 4 }}>
      {!hideHeader && header != null && header !== "" && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            height: T.stepHeaderHeight,
            paddingLeft: 4,
          }}
        >
          <View
            style={{
              flex: 1,
              minWidth: 0,
              paddingTop: T.stepTopPadding,
              paddingLeft: T.timelineCommonTextPadding,
            }}
          >
            {typeof header === "string" || typeof header === "number" ? (
              <Text font="main-ui-muted" color="text-04" numberOfLines={1}>
                {header}
              </Text>
            ) : (
              header
            )}
          </View>

          <View
            style={{
              height: "100%",
              width: T.stepHeaderRightSectionWidth,
              alignItems: "flex-end",
              justifyContent: "center",
            }}
          >
            {showCollapseControls ? (
              <Pressable
                onPress={onToggle}
                hitSlop={8}
                accessibilityRole="button"
                style={{ padding: 4 }}
              >
                <ToggleIcon size={16} color="text-03" />
              </Pressable>
            ) : surfaceBackground === "error" ? (
              <View style={{ padding: 6 }}>
                <SvgXOctagon size={16} color={errorColor} />
              </View>
            ) : null}
          </View>
        </View>
      )}

      {children != null && (
        <View
          style={{
            paddingLeft: 4,
            paddingBottom: 4,
            paddingRight: noPaddingRight ? 0 : T.stepHeaderRightSectionWidth,
            paddingTop: hideHeader ? T.stepTopPadding : 0,
          }}
        >
          {children}
        </View>
      )}
    </View>
  );
}

export default TimelineStepContent;
