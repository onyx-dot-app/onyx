import React, { FunctionComponent } from "react";
import { cn } from "@/lib/utils";
import { IconProps } from "@opal/types";
import { TimelineRow } from "@/app/app/message/messageComponents/timeline/primitives/TimelineRow";
import { TimelineSurface } from "@/app/app/message/messageComponents/timeline/primitives/TimelineSurface";
import { TimelineStepContent } from "@/app/app/message/messageComponents/timeline/primitives/TimelineStepContent";

export interface StepContainerProps {
  /** Main content */
  children?: React.ReactNode;
  /** Step icon component */
  stepIcon?: FunctionComponent<IconProps>;
  /** Header left slot */
  header?: React.ReactNode;
  /** Button title for toggle */
  buttonTitle?: string;
  /** Controlled expanded state */
  isExpanded?: boolean;
  /** Toggle callback */
  onToggle?: () => void;
  /** Whether collapse control is shown */
  collapsible?: boolean;
  /** Collapse button shown only when renderer supports collapsible mode */
  supportsCollapsible?: boolean;
  /** Last step (no bottom connector) */
  isLastStep?: boolean;
  /** First step (top padding instead of connector) */
  isFirstStep?: boolean;
  /** Hide header (single-step timelines) */
  hideHeader?: boolean;
  /** Hover state from parent */
  isHover?: boolean;
  /** Custom icon to show when collapsed (defaults to SvgExpand) */
  collapsedIcon?: FunctionComponent<IconProps>;
  /** Remove right padding (for reasoning content) */
  noPaddingRight?: boolean;
  /** Render without rail (for nested/parallel content) */
  withRail?: boolean;
}

/** Visual wrapper for timeline steps - icon, connector line, header, and content */
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
  isHover = false,
  collapsedIcon: CollapsedIconComponent,
  noPaddingRight = false,
  withRail = true,
}: StepContainerProps) {
  const iconNode = StepIconComponent ? (
    <StepIconComponent
      className={cn(
        "h-[var(--timeline-icon-size)] w-[var(--timeline-icon-size)] stroke-text-02",
        isHover && "stroke-text-04"
      )}
    />
  ) : null;

  const content = (
    <TimelineSurface
      className="flex-1 flex flex-col"
      isHover={isHover}
      roundedBottom={isLastStep}
    >
      <TimelineStepContent
        header={header}
        buttonTitle={buttonTitle}
        isExpanded={isExpanded}
        onToggle={onToggle}
        collapsible={collapsible}
        supportsCollapsible={supportsCollapsible}
        hideHeader={hideHeader}
        collapsedIcon={CollapsedIconComponent}
        noPaddingRight={noPaddingRight}
      >
        {children}
      </TimelineStepContent>
    </TimelineSurface>
  );

  if (!withRail) {
    return <div className="flex w-full">{content}</div>;
  }

  return (
    <TimelineRow
      railVariant="rail"
      icon={iconNode}
      showIcon={!hideHeader && Boolean(StepIconComponent)}
      iconRowVariant={hideHeader ? "compact" : "default"}
      isFirst={isFirstStep}
      isLast={isLastStep}
      isHover={isHover}
    >
      {content}
    </TimelineRow>
  );
}

export default StepContainer;
