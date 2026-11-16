import React, { FunctionComponent } from "react";
import type { IconFunctionComponent, IconProps, RichStr } from "@opal/types";
import { Button, Log } from "@opal/components";
import { SvgChevronRight } from "@opal/icons";
import { cn } from "@opal/utils";
import type { TimelineSurfaceBackground } from "@/lib/timeline/components/primitives/TimelineSurface";
import { STEP_ICONS } from "@/lib/timeline/icons";

export interface StepContainerProps {
  /** Main content */
  children?: React.ReactNode;
  /** Step icon component */
  stepIcon?: FunctionComponent<IconProps>;
  /** The step's title, in the log line's title column */
  header?: string | RichStr;
  /** What the step acted on (a command, a path), after the title */
  detail?: React.ReactNode;
  /** Rendered at the inline end of the line, before the fold button */
  headerAccessory?: React.ReactNode;
  /** Controlled expanded state */
  isExpanded?: boolean;
  /** Toggle callback */
  onToggle?: () => void;
  /** Whether collapse control is shown */
  collapsible?: boolean;
  /** Collapse button shown only when renderer supports collapsible mode */
  supportsCollapsible?: boolean;
  /** Last step of the run */
  isLastStep?: boolean;
  /** First step of the run */
  isFirstStep?: boolean;
  /** Hide header (the body is its own control) */
  hideHeader?: boolean;
  /** Hover state from parent */
  isHover?: boolean;
  /** `error` shows the step as a failed log line */
  surfaceBackground?: TimelineSurfaceBackground;
}

/**
 * One step of a run, as an Opal `Log` line: the icon, the title and its
 * detail, and the body folding open below it. A failed step is an
 * `error-heavy` line, tinted with its body.
 */
export function StepContainer({
  children,
  stepIcon,
  header,
  detail,
  headerAccessory,
  isExpanded = true,
  onToggle,
  collapsible = true,
  supportsCollapsible = false,
  hideHeader = false,
  surfaceBackground,
}: StepContainerProps) {
  if (hideHeader) return <>{children}</>;

  const variant = surfaceBackground === "error" ? "error-heavy" : "default";
  const icon = (stepIcon ?? STEP_ICONS.thinking) as IconFunctionComponent;
  const title = header ?? "";
  const foldable = collapsible && supportsCollapsible && !!onToggle;

  if (!foldable) {
    return (
      <>
        <Log
          padding={0}
          variant={variant}
          icon={icon}
          title={title}
          centerChildren={detail}
          rightChildren={headerAccessory}
        />
        {children}
      </>
    );
  }

  return (
    <Log
      padding={0}
      variant={variant}
      icon={icon}
      title={title}
      centerChildren={detail}
      rightChildren={headerAccessory}
      onClick={onToggle}
      endButton={
        // As in the connector check card: points right closed and turns down
        // open. Its click reaches the line's, which toggles the step.
        <div
          className={cn(
            "transition-transform duration-200 ease-in-out",
            isExpanded && "rotate-90"
          )}
        >
          <Button
            icon={SvgChevronRight}
            prominence="tertiary"
            size="md"
            aria-expanded={isExpanded}
          />
        </div>
      }
      expandable
      expanded={isExpanded}
      expandedContent={children}
    />
  );
}

export default StepContainer;
