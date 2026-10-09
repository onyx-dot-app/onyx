// Visual wrapper for one timeline step — rail icon + connector, tint/error surface, header, body.
// Hover dropped: the node icon rests at text-02. The renderer supplies icon/header/content.
import type { ReactNode } from "react";
import { View } from "react-native";

import { Icon } from "@/components/ui/icon";
import type { TimelineSurfaceBackground } from "@/components/chat/renderers/timelineContract";
import type { IconFunctionComponent } from "@/icons/types";

import { timelineTokens } from "./primitives/timelineTokens";
import { TimelineRow } from "./primitives/TimelineRow";
import { TimelineStepContent } from "./primitives/TimelineStepContent";
import { TimelineSurface } from "./primitives/TimelineSurface";

export interface StepContainerProps {
  children?: ReactNode;
  stepIcon?: IconFunctionComponent;
  header?: ReactNode;
  buttonTitle?: string;
  isExpanded?: boolean;
  onToggle?: () => void;
  collapsible?: boolean;
  supportsCollapsible?: boolean;
  isLastStep?: boolean;
  isFirstStep?: boolean;
  hideHeader?: boolean;
  collapsedIcon?: IconFunctionComponent;
  noPaddingRight?: boolean;
  // Render without the rail (nested/parallel content).
  withRail?: boolean;
  surfaceBackground?: TimelineSurfaceBackground;
}

export function StepContainer({
  children,
  stepIcon: StepIconComponent,
  header,
  buttonTitle,
  isExpanded = true,
  onToggle,
  collapsible = true,
  supportsCollapsible = false,
  isLastStep = false,
  isFirstStep = false,
  hideHeader = false,
  collapsedIcon,
  noPaddingRight = false,
  withRail = true,
  surfaceBackground,
}: StepContainerProps) {
  const iconNode = StepIconComponent ? (
    <Icon
      as={StepIconComponent}
      size={timelineTokens.iconSize}
      className="text-text-02"
    />
  ) : null;

  const content = (
    <TimelineSurface
      className="flex-1"
      roundedBottom={isLastStep}
      background={surfaceBackground}
    >
      <TimelineStepContent
        header={header}
        buttonTitle={buttonTitle}
        isExpanded={isExpanded}
        onToggle={onToggle}
        collapsible={collapsible}
        supportsCollapsible={supportsCollapsible}
        hideHeader={hideHeader}
        collapsedIcon={collapsedIcon}
        noPaddingRight={noPaddingRight}
        surfaceBackground={surfaceBackground}
      >
        {children}
      </TimelineStepContent>
    </TimelineSurface>
  );

  if (!withRail) {
    return <View className="w-full flex-row">{content}</View>;
  }

  return (
    <TimelineRow
      railVariant="rail"
      icon={iconNode}
      showIcon={!hideHeader && Boolean(StepIconComponent)}
      iconRowVariant={hideHeader ? "compact" : "default"}
      isFirst={isFirstStep}
      isLast={isLastStep}
    >
      {content}
    </TimelineRow>
  );
}

export default StepContainer;
