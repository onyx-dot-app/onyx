import React, { FunctionComponent } from "react";
import { cn } from "@/lib/utils";
import { SvgFold, SvgExpand, SvgXOctagon } from "@opal/icons";
import { IconProps } from "@opal/types";
import { Button } from "@opal/components";
// TODO(@raunakab): migrate this `refresh-components/Text` to `@opal/components` Text
import Text from "@/refresh-components/texts/Text";
import { TimelineSurfaceBackground } from "@/app/app/message/messageComponents/timeline/primitives/TimelineSurface";

export interface TimelineStepContentProps {
  children?: React.ReactNode;
  header?: React.ReactNode;
  buttonTitle?: string;
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
  const showCollapseControls = collapsible && supportsCollapsible && onToggle;

  return (
    <div className="flex flex-col px-1 pb-1">
      {!hideHeader && header && (
        <div className="flex items-center justify-between h-[var(--timeline-step-header-height)] pl-1">
          <div className="pt-[var(--timeline-step-top-padding)] pl-[var(--timeline-common-text-padding)] w-full">
            <Text as="p" mainUiMuted text04>
              {header}
            </Text>
          </div>

          <div className="h-full w-[var(--timeline-step-header-right-section-width)] flex items-center justify-end">
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
            "pl-1 pb-1",
            !noPaddingRight &&
              "pr-[var(--timeline-step-header-right-section-width)]",
            hideHeader && "pt-[var(--timeline-step-top-padding)]"
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

export default TimelineStepContent;
