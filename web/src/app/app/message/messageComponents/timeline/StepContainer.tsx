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
  /** Collapse button shown only when renderer supports compact mode */
  supportsCompact?: boolean;
  /** Additional class names */
  className?: string;
  /** Last step (no bottom connector) */
  isLastStep?: boolean;
  /** First step (top padding instead of connector) */
  isFirstStep?: boolean;
  /** Hide header (single-step timelines) */
  hideHeader?: boolean;
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
  supportsCompact = false,
  isLastStep = false,
  isFirstStep = false,
  className,
  hideHeader = false,
}: StepContainerProps) {
  const showCollapseControls = collapsible && supportsCompact && onToggle;

  return (
    <div className={cn("flex w-full", className)}>
      <div
        className={cn("flex flex-col items-center w-9", isFirstStep && "pt-2")}
      >
        {/* Icon */}
        {!hideHeader && StepIconComponent && (
          <div className="py-1">
            <StepIconComponent className="size-4 stroke-text-02" />
          </div>
        )}

        {/* Connector line */}
        {!isLastStep && <div className="w-px flex-1 bg-border-01" />}
      </div>

      <div
        className={cn(
          "w-full bg-background-tint-00",
          isLastStep && "rounded-b-12"
        )}
      >
        {!hideHeader && (
          <div className="flex items-center justify-between px-2">
            {header && (
              <Text as="p" mainUiMuted text03>
                {header}
              </Text>
            )}

            {showCollapseControls &&
              (buttonTitle ? (
                <Button
                  tertiary
                  onClick={onToggle}
                  rightIcon={isExpanded ? SvgFold : SvgExpand}
                >
                  {buttonTitle}
                </Button>
              ) : (
                <IconButton
                  tertiary
                  onClick={onToggle}
                  icon={isExpanded ? SvgFold : SvgExpand}
                />
              ))}
          </div>
        )}

        <div className="px-2 pb-2">{children}</div>
      </div>
    </div>
  );
}

export default StepContainer;
