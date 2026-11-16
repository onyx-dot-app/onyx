import React, { FunctionComponent } from "react";
import { cn } from "@opal/utils";
import { SvgXOctagon } from "@opal/icons";
import type { IconProps, RichStr } from "@opal/types";
import { Content } from "@opal/layouts";
import { Collapsible } from "@opal/components";
import { TimelineSurfaceBackground } from "@/lib/timeline/components/primitives/TimelineSurface";

export interface TimelineStepContentProps {
  children?: React.ReactNode;
  /** The step's icon, at the title's size. */
  icon?: FunctionComponent<IconProps>;
  header?: string | RichStr;
  /** Rendered at the inline end of the header, before the toggle. */
  headerAccessory?: React.ReactNode;
  isExpanded?: boolean;
  onToggle?: () => void;
  collapsible?: boolean;
  supportsCollapsible?: boolean;
  hideHeader?: boolean;
  surfaceBackground?: TimelineSurfaceBackground;
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
  isExpanded = true,
  onToggle,
  collapsible = true,
  supportsCollapsible = false,
  hideHeader = false,
  surfaceBackground,
}: TimelineStepContentProps) {
  const showCollapseControls = collapsible && supportsCollapsible && onToggle;
  const body = (
    <div
      className={cn(
        // Under the title: past the header's inset and the 1rem icon box.
        "ps-5",
        hideHeader && "pt-(--timeline-step-top-padding)"
      )}
    >
      {children}
    </div>
  );

  // Opal's Collapsible parts: the root holds the step's open state, the fold
  // button is the trigger, and the body folds in Collapsible.Content.
  return (
    <Collapsible.Root open={isExpanded} onOpenChange={() => onToggle?.()}>
      <div className="flex flex-col">
        {/* The 16px title line plus 6px each side is 28px, the md fold
            button's height, so a row without a button is as tall. */}
        {!hideHeader &&
          header &&
          (showCollapseControls ? (
            <Collapsible.Header
              name={header}
              size="md"
              rightChildren={headerAccessory}
            >
              <div className="ps-1 py-1.5">
                <Content
                  icon={icon}
                  title={header}
                  font="secondary-body"
                  titleColor="text-03"
                  titleMaxLines={1}
                />
              </div>
            </Collapsible.Header>
          ) : (
            <div className="flex items-center">
              <div className="flex-1 min-w-0">
                <div className="ps-1 py-1.5">
                  <Content
                    icon={icon}
                    title={header}
                    font="secondary-body"
                    titleColor="text-03"
                    titleMaxLines={1}
                  />
                </div>
              </div>
              {headerAccessory && (
                <div className="shrink-0 ps-2">{headerAccessory}</div>
              )}
              {surfaceBackground === "error" && (
                <div className="shrink-0 p-1.5">
                  <SvgXOctagon className="h-4 w-4 text-status-error-05" />
                </div>
              )}
            </div>
          ))}

        {children && <Collapsible.Content>{body}</Collapsible.Content>}
      </div>
    </Collapsible.Root>
  );
}

export default TimelineStepContent;
