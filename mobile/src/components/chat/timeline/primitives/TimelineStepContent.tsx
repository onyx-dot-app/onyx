// Step header (status + collapse control) + body. The collapse control reuses the mobile Button
// (tertiary/md) — the parity primitive for web's tertiary icon button. No hover, so it's always
// visible when the renderer supports collapsing. A string header wraps in Text; a ReactElement header
// renders as-is (RN Text can't nest arbitrary views).
import type { ReactNode } from "react";
import { View } from "react-native";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import type { TimelineSurfaceBackground } from "@/components/chat/renderers/timelineContract";
import SvgExpand from "@/icons/expand";
import SvgFold from "@/icons/fold";
import type { IconFunctionComponent } from "@/icons/types";
import SvgXOctagon from "@/icons/x-octagon";

import { timelineTokens } from "./timelineTokens";

export interface TimelineStepContentProps {
  children?: ReactNode;
  header?: ReactNode;
  buttonTitle?: string;
  isExpanded?: boolean;
  onToggle?: () => void;
  collapsible?: boolean;
  supportsCollapsible?: boolean;
  hideHeader?: boolean;
  collapsedIcon?: IconFunctionComponent;
  noPaddingRight?: boolean;
  surfaceBackground?: TimelineSurfaceBackground;
}

export function TimelineStepContent({
  children,
  header,
  buttonTitle,
  isExpanded = true,
  onToggle,
  collapsible = true,
  supportsCollapsible = false,
  hideHeader = false,
  collapsedIcon: CollapsedIconComponent,
  noPaddingRight = false,
  surfaceBackground,
}: TimelineStepContentProps) {
  const showCollapseControls = collapsible && supportsCollapsible && !!onToggle;
  const toggleIcon = isExpanded
    ? SvgFold
    : (CollapsedIconComponent ?? SvgExpand);

  return (
    <View className="px-4 pb-4">
      {!hideHeader && header != null && (
        <View
          className="flex-row items-center justify-between pl-4"
          style={{ height: timelineTokens.stepHeaderHeight }}
        >
          <View
            className="flex-1"
            style={{
              paddingTop: timelineTokens.stepTopPadding,
              paddingLeft: timelineTokens.timelineCommonTextPadding,
            }}
          >
            {typeof header === "string" ? (
              <Text font="main-ui-muted" color="text-04">
                {header}
              </Text>
            ) : (
              header
            )}
          </View>

          <View
            className="h-full flex-row items-center justify-end"
            style={{ width: timelineTokens.stepHeaderRightSectionWidth }}
          >
            {showCollapseControls ? (
              buttonTitle ? (
                <Button
                  prominence="tertiary"
                  size="md"
                  onPress={onToggle}
                  rightIcon={toggleIcon}
                >
                  {buttonTitle}
                </Button>
              ) : (
                <Button
                  prominence="tertiary"
                  size="md"
                  onPress={onToggle}
                  icon={toggleIcon}
                  accessibilityLabel={isExpanded ? "Collapse" : "Expand"}
                />
              )
            ) : surfaceBackground === "error" ? (
              <View className="p-6">
                <Icon
                  as={SvgXOctagon}
                  size={16}
                  className="text-status-error-05"
                />
              </View>
            ) : null}
          </View>
        </View>
      )}

      {children != null && (
        <View
          className="pb-4 pl-4"
          style={{
            paddingRight: noPaddingRight
              ? undefined
              : timelineTokens.stepHeaderRightSectionWidth,
            paddingTop: hideHeader ? timelineTokens.stepTopPadding : undefined,
          }}
        >
          {children}
        </View>
      )}
    </View>
  );
}

export default TimelineStepContent;
