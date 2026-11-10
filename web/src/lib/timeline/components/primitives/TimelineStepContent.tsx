import React, { FunctionComponent } from "react";
import { cn, richNodes } from "@opal/utils";
import { SvgFold, SvgExpand, SvgXOctagon } from "@opal/icons";
import { IconProps } from "@opal/types";
import { Button, Text } from "@opal/components";
import { TimelineSurfaceBackground } from "@/lib/timeline/components/primitives/TimelineSurface";

export interface TimelineStepContentProps {
  children?: React.ReactNode;
  header?: React.ReactNode;
  /** Rendered at the inline end of the header, before the toggle. */
  headerAccessory?: React.ReactNode;
  buttonTitle?: string;
  /** Accessible name of the icon-only toggle (no `buttonTitle`). */
  toggleLabel?: string;
  isExpanded?: boolean;
  onToggle?: () => void;
  collapsible?: boolean;
  supportsCollapsible?: boolean;
  hideHeader?: boolean;
  collapsedIcon?: FunctionComponent<IconProps>;
  noPaddingRight?: boolean;
  surfaceBackground?: TimelineSurfaceBackground;
}

/**
 * TimelineStepContent renders the header row + content body for a step.
 * It is used by StepContainer and by parallel tab content to keep layout consistent.
 */
export function TimelineStepContent({
  children,
  header,
  headerAccessory,
  buttonTitle,
  toggleLabel,
  isExpanded = true,
  onToggle,
  collapsible = true,
  supportsCollapsible = false,
  hideHeader = false,
  collapsedIcon: CollapsedIconComponent,
  noPaddingRight = false,
  surfaceBackground,
}: TimelineStepContentProps) {
  const showCollapseControls = collapsible && supportsCollapsible && onToggle;

  return (
    <div className="flex flex-col px-1 pb-1">
      {!hideHeader && header && (
        <div className="flex items-center justify-between h-(--timeline-step-header-height) ps-1">
          <div className="pt-(--timeline-step-top-padding) ps-(--timeline-common-text-padding) w-full min-w-0">
            <Text as="p" font="main-ui-muted" color="text-04">
              {richNodes(header)}
            </Text>
          </div>

          {headerAccessory && (
            <div className="shrink-0 pt-(--timeline-step-top-padding) ps-2">
              {headerAccessory}
            </div>
          )}

          <div className="h-full w-(--timeline-step-header-right-section-width) flex items-center justify-end">
            {showCollapseControls ? (
              buttonTitle ? (
                <Button
                  prominence="tertiary"
                  size="md"
                  onClick={onToggle}
                  rightIcon={
                    isExpanded ? SvgFold : CollapsedIconComponent || SvgExpand
                  }
                >
                  {buttonTitle}
                </Button>
              ) : (
                <Button
                  prominence="tertiary"
                  size="md"
                  onClick={onToggle}
                  aria-label={toggleLabel}
                  aria-expanded={isExpanded}
                  icon={
                    isExpanded ? SvgFold : CollapsedIconComponent || SvgExpand
                  }
                />
              )
            ) : surfaceBackground === "error" ? (
              <div className="p-1.5">
                <SvgXOctagon className="h-4 w-4 text-status-error-05" />
              </div>
            ) : null}
          </div>
        </div>
      )}

      {children && (
        <div
          className={cn(
            "ps-1 pb-1",
            !noPaddingRight &&
              "pe-(--timeline-step-header-right-section-width)",
            hideHeader && "pt-(--timeline-step-top-padding)"
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

export default TimelineStepContent;
