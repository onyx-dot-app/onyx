import React, { FunctionComponent } from "react";
import type { IconFunctionComponent, IconProps, RichStr } from "@opal/types";
import { FoldButton, Line, type LineVariant } from "@opal/components";
import { Section } from "@opal/layouts";
import type { TimelineSurfaceBackground } from "@/lib/timeline/components/primitives/TimelineSurface";
import { STEP_ICONS } from "@/lib/timeline/icons";

export interface StepContainerProps {
  /** Main content */
  children?: React.ReactNode;
  /** Step icon component */
  stepIcon?: FunctionComponent<IconProps>;
  /** The step's title; it fills the line */
  header?: string | RichStr;
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
  /** The line's variant; it wins over `surfaceBackground`. */
  variant?: LineVariant;
}

/**
 * One step of a run, as an Opal `Line`: the icon, the title, trailing
 * content and the chevron, and the body folding open below it. A failed step
 * is an `error-heavy` line, tinted with its body.
 */
export function StepContainer({
  children,
  stepIcon,
  header,
  headerAccessory,
  isExpanded = true,
  onToggle,
  collapsible = true,
  supportsCollapsible = false,
  hideHeader = false,
  surfaceBackground,
  variant: variantProp,
}: StepContainerProps) {
  if (hideHeader) return <>{children}</>;

  const variant: LineVariant =
    variantProp ?? (surfaceBackground === "error" ? "error-heavy" : "default");
  const icon = (stepIcon ?? STEP_ICONS.thinking) as IconFunctionComponent;
  const title = header ?? "";
  const foldable = collapsible && supportsCollapsible && !!onToggle;

  // A step that cannot fold keeps its body open, so every step's body has the
  // same place under its header.
  if (!foldable) {
    const line = {
      padding: 0,
      variant,
      icon,
      title,
      rightChildren: headerAccessory,
    } as const;
    return children == null || children === false ? (
      <Line {...line} />
    ) : (
      <Line {...line} expandable expanded expandedContent={children} />
    );
  }

  return (
    <Line
      padding={0}
      variant={variant}
      icon={icon}
      title={title}
      onClick={onToggle}
      rightChildren={
        <Section flexDirection="row" width="fit" height="fit" gap={1}>
          {headerAccessory}
          {/* Its click reaches the line's, which toggles the step. */}
          <FoldButton open={isExpanded} size="md" />
        </Section>
      }
      expandable
      expanded={isExpanded}
      expandedContent={children}
    />
  );
}

export default StepContainer;
