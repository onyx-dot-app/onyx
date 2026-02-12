import React, { FunctionComponent } from "react";
import { cn } from "@/lib/utils";
import { SvgFold, SvgExpand } from "@opal/icons";
import { IconProps } from "@opal/types";
import Button from "@/refresh-components/buttons/Button";
import { Button as OpalButton } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { TimelineTopSpacer } from "./TimelineTopSpacer";
import { TimelineTopSpacerVariant } from "./tokens";

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
            {showCollapseControls &&
              (buttonTitle ? (
                <Button
                  size="md"
                  tertiary
                  onClick={onToggle}
                  rightIcon={
                    isExpanded ? SvgFold : CollapsedIconComponent || SvgExpand
                  }
                >
                  {buttonTitle}
                </Button>
              ) : (
                <OpalButton
                  prominence="tertiary"
                  size="sm"
                  onClick={onToggle}
                  icon={
                    isExpanded ? SvgFold : CollapsedIconComponent || SvgExpand
                  }
                />
              ))}
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
