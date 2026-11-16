import React, { FunctionComponent } from "react";
import type { IconProps, RichStr } from "@opal/types";
import {
  TimelineSurface,
  TimelineSurfaceBackground,
} from "@/lib/timeline/components/primitives/TimelineSurface";
import { TimelineStepContent } from "@/lib/timeline/components/primitives/TimelineStepContent";

export interface StepContainerProps {
  /** Main content */
  children?: React.ReactNode;
  /** Step icon component */
  stepIcon?: FunctionComponent<IconProps>;
  /** The step's title, beside its icon */
  header?: string | RichStr;
  /** Rendered at the inline end of the header, before the toggle */
  headerAccessory?: React.ReactNode;
  /** Controlled expanded state */
  isExpanded?: boolean;
  /** Toggle callback */
  onToggle?: () => void;
  /** Whether collapse control is shown */
  collapsible?: boolean;
  /** Collapse button shown only when renderer supports collapsible mode */
  supportsCollapsible?: boolean;
  /** Last step: rounded at the bottom of the card */
  isLastStep?: boolean;
  /** First step of the run */
  isFirstStep?: boolean;
  /** Hide header (single-step timelines) */
  hideHeader?: boolean;
  /** Hover state from parent */
  isHover?: boolean;
  /** Override the surface background variant */
  surfaceBackground?: TimelineSurfaceBackground;
}

/** One step of a run: its header (icon and title, as `Content`) and its body, on the run card's surface. */
export function StepContainer({
  children,
  stepIcon,
  header,
  headerAccessory,
  isExpanded = true,
  onToggle,
  collapsible = true,
  supportsCollapsible = false,
  isLastStep = false,
  hideHeader = false,
  isHover = false,
  surfaceBackground,
}: StepContainerProps) {
  return (
    <TimelineSurface
      isHover={isHover}
      roundedBottom={isLastStep}
      background={surfaceBackground}
    >
      <TimelineStepContent
        icon={stepIcon}
        header={header}
        headerAccessory={headerAccessory}
        isExpanded={isExpanded}
        onToggle={onToggle}
        collapsible={collapsible}
        supportsCollapsible={supportsCollapsible}
        hideHeader={hideHeader}
        surfaceBackground={surfaceBackground}
      >
        {children}
      </TimelineStepContent>
    </TimelineSurface>
  );
}

export default StepContainer;
