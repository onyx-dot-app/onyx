// Native mirror of web StepContainer. stepIconName is a TimelineIconName
// (not a component) mapped to an Svg* via TimelineIcon.

import type { ReactNode } from "react";
import { View } from "react-native";

import { TimelineRow } from "@/components/message/timeline/primitives/TimelineRow";
import { TimelineSurface } from "@/components/message/timeline/primitives/TimelineSurface";
import { TimelineStepContent } from "@/components/message/timeline/primitives/TimelineStepContent";
import { TimelineIcon } from "@/components/message/timeline/toolIcon";
import { timelineTokens as T } from "@/theme/timelineTokens";
import type { TimelineSurfaceBackground } from "@/components/message/interfaces";
import type { TimelineIconName } from "@/state/timeline/toolDisplayHelpers";

export interface StepContainerProps {
  children?: ReactNode;
  stepIconName?: TimelineIconName | null;
  header?: ReactNode;
  isExpanded?: boolean;
  onToggle?: () => void;
  collapsible?: boolean;
  supportsCollapsible?: boolean;
  isLastStep?: boolean;
  isFirstStep?: boolean;
  hideHeader?: boolean;
  noPaddingRight?: boolean;
  withRail?: boolean;
  surfaceBackground?: TimelineSurfaceBackground;
}

export function StepContainer({
  children,
  stepIconName,
  header,
  isExpanded = true,
  onToggle,
  collapsible = true,
  supportsCollapsible = false,
  isLastStep = false,
  isFirstStep = false,
  hideHeader = false,
  noPaddingRight = false,
  withRail = true,
  surfaceBackground,
}: StepContainerProps) {
  const iconNode = stepIconName ? (
    <TimelineIcon name={stepIconName} size={T.iconSize} color="text-02" />
  ) : null;

  const content = (
    <TimelineSurface
      roundedBottom={isLastStep}
      background={surfaceBackground}
    >
      <TimelineStepContent
        header={header}
        isExpanded={isExpanded}
        onToggle={onToggle}
        collapsible={collapsible}
        supportsCollapsible={supportsCollapsible}
        hideHeader={hideHeader}
        noPaddingRight={noPaddingRight}
        surfaceBackground={surfaceBackground}
      >
        {children}
      </TimelineStepContent>
    </TimelineSurface>
  );

  if (!withRail) {
    return <View style={{ flexDirection: "row", width: "100%" }}>{content}</View>;
  }

  return (
    <TimelineRow
      railVariant="rail"
      icon={iconNode}
      showIcon={!hideHeader && Boolean(stepIconName)}
      iconRowVariant={hideHeader ? "compact" : "default"}
      isFirst={isFirstStep}
      isLast={isLastStep}
    >
      {content}
    </TimelineRow>
  );
}

export default StepContainer;
