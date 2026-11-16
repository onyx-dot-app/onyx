import React, { FunctionComponent } from "react";
import { cn } from "@opal/utils";
import { SvgFold, SvgExpand, SvgXOctagon } from "@opal/icons";
import type { IconProps, RichStr } from "@opal/types";
import { Content } from "@opal/layouts";
import { Button, Collapsible } from "@opal/components";
import { TimelineSurfaceBackground } from "@/lib/timeline/components/primitives/TimelineSurface";

export interface TimelineStepContentProps {
  children?: React.ReactNode;
  /** The step's icon, at the title's size. */
  icon?: FunctionComponent<IconProps>;
  header?: string | RichStr;
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
  /** Fold the body open and closed with `isExpanded`, animated. */
  foldBody?: boolean;
}

/**
 * TimelineStepContent renders the header row + content body for a step.
 * It is used by StepContainer and by parallel tab content to keep layout consistent.
 */
export function TimelineStepContent({
  children,
  icon,
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
  foldBody = false,
}: TimelineStepContentProps) {
  const showCollapseControls = collapsible && supportsCollapsible && onToggle;
  const body = (
    <div
      className={cn(
        // Under the title: past the header's inset and the 1rem icon box.
        "ps-5 pb-1",
        !noPaddingRight && "pe-(--timeline-step-header-right-section-width)",
        hideHeader && "pt-(--timeline-step-top-padding)"
      )}
    >
      {children}
    </div>
  );

  return (
    <div className="flex flex-col px-1 pb-1">
      {!hideHeader && header && (
        <div className="flex items-center justify-between h-(--timeline-step-header-height) ps-1">
          {/* Positioned so it paints over the rail line; the icon box takes the
              surface colour to mask the line. */}
          <div className="relative flex-1 min-w-0 [&_.opal-content-icon]:bg-(--timeline-surface)">
            <Content
              icon={icon}
              title={header}
              font="secondary-body"
              titleColor="text-03"
              titleMaxLines={1}
            />
          </div>

          {headerAccessory && (
            <div className="shrink-0 ps-2">{headerAccessory}</div>
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

      {children &&
        (foldBody ? (
          <Collapsible.Root open={isExpanded} onOpenChange={onToggle}>
            <Collapsible.Content>{body}</Collapsible.Content>
          </Collapsible.Root>
        ) : (
          body
        ))}
    </div>
  );
}

export default TimelineStepContent;
