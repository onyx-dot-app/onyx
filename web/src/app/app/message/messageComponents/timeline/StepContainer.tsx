import React, { FunctionComponent } from "react";
import { cn } from "@/lib/utils";
import { SvgFold, SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import { IconProps } from "@opal/types";
import Text from "@/refresh-components/texts/Text";

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
  /** Additional class names */
  className?: string;
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
  className,
  hideHeader = false,
  isHover = false,
  collapsedIcon: CollapsedIconComponent,
  noPaddingRight = false,
}: StepContainerProps) {
  const showCollapseControls = collapsible && supportsCollapsible && onToggle;

  return (
    <div className={cn("flex w-full", className)}>
      <div
        className={cn(
          "flex flex-col items-center w-9",
          isFirstStep && "pt-0.5",
          !isFirstStep && "pt-1.5"
        )}
      >
        {/* Icon */}
        {!hideHeader && StepIconComponent && (
          <div className="flex py-1 h-8 items-center justify-center">
            <StepIconComponent
              className={cn(
                "size-3 stroke-text-02",
                isHover && "stroke-text-04"
              )}
            />
          </div>
        )}

        {/* Connector line */}
        {!isLastStep && (
          <div
            className={cn(
              "w-px h-full bg-border-01",
              isHover && "bg-border-04"
            )}
          />
        )}
      </div>

      <div
        className={cn(
          "w-full bg-background-tint-00 transition-colors duration-200",
          isLastStep && "rounded-b-12",
          isHover && "bg-background-tint-02"
        )}
      >
        {!hideHeader && header && (
          <div className="flex items-center justify-between pl-2 pr-1 h-8">
            <Text as="p" mainUiMuted text04>
              {header}
            </Text>

            {showCollapseControls &&
              (buttonTitle ? (
                <Button
                  tertiary
                  onClick={onToggle}
                  rightIcon={
                    isExpanded ? SvgFold : CollapsedIconComponent || SvgExpand
                  }
                >
                  {buttonTitle}
                </Button>
              ) : (
                <IconButton
                  tertiary
                  onClick={onToggle}
                  icon={
                    isExpanded ? SvgFold : CollapsedIconComponent || SvgExpand
                  }
                />
              ))}
          </div>
        )}

        <div className={cn("pl-2 pb-2", !noPaddingRight && "pr-8")}>
          {children}
        </div>
      </div>
    </div>
  );
}

export default StepContainer;
