import React, { FunctionComponent } from "react";
import { cn } from "@opal/utils";
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
  /** Button title for toggle */
  buttonTitle?: string;
  /** Accessible name of the icon-only toggle */
  toggleLabel?: string;
  /** Controlled expanded state */
  isExpanded?: boolean;
  /** Toggle callback */
  onToggle?: () => void;
  /** Whether collapse control is shown */
  collapsible?: boolean;
  /** Collapse button shown only when renderer supports collapsible mode */
  supportsCollapsible?: boolean;
  /** Last step: no rail line below its icon */
  isLastStep?: boolean;
  /** First step; kept for callers, the rail starts at the first icon anyway */
  isFirstStep?: boolean;
  /** Hide header (single-step timelines) */
  hideHeader?: boolean;
  /** Hover state from parent */
  isHover?: boolean;
  /** Custom icon to show when collapsed (defaults to SvgExpand) */
  collapsedIcon?: FunctionComponent<IconProps>;
  /** Remove right padding (for reasoning content) */
  noPaddingRight?: boolean;
  /** Override the surface background variant */
  surfaceBackground?: TimelineSurfaceBackground;
  /** Fold the body open and closed with `isExpanded`, animated. */
  foldBody?: boolean;
}

/**
 * One step of a run: its header (icon and title, as `Content`) and its body,
 * on the run card's surface. The rail is a line from this step's icon to the
 * next step's icon, placed absolutely, so it needs no column of its own.
 */
export function StepContainer({
  children,
  stepIcon,
  header,
  headerAccessory,
  buttonTitle,
  toggleLabel,
  isExpanded = true,
  onToggle,
  collapsible = true,
  supportsCollapsible = false,
  isLastStep = false,
  hideHeader = false,
  isHover = false,
  collapsedIcon,
  noPaddingRight = false,
  surfaceBackground,
  foldBody = false,
}: StepContainerProps) {
  return (
    <TimelineSurface
      className="relative"
      isHover={isHover}
      roundedBottom={isLastStep}
      background={surfaceBackground}
    >
      {!isLastStep && (
        // From this step's header centre to the next step's, behind both
        // icons; each icon box masks it, so it shows between them, centred.
        <div
          aria-hidden
          className={cn(
            "absolute start-4 -bottom-4 w-px",
            hideHeader ? "top-0" : "top-4",
            isHover ? "bg-border-04" : "bg-border-01"
          )}
        />
      )}
      <TimelineStepContent
        icon={stepIcon}
        header={header}
        headerAccessory={headerAccessory}
        buttonTitle={buttonTitle}
        toggleLabel={toggleLabel}
        isExpanded={isExpanded}
        onToggle={onToggle}
        collapsible={collapsible}
        supportsCollapsible={supportsCollapsible}
        hideHeader={hideHeader}
        collapsedIcon={collapsedIcon}
        noPaddingRight={noPaddingRight}
        surfaceBackground={surfaceBackground}
        foldBody={foldBody}
      >
        {children}
      </TimelineStepContent>
    </TimelineSurface>
  );
}

export default StepContainer;
