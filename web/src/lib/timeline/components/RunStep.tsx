"use client";

import React, { useState } from "react";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { StepContainer } from "@/lib/timeline/components/StepContainer";
import type { TimelineSurfaceBackground } from "@/lib/timeline/components/primitives/TimelineSurface";
import { STEP_ICONS } from "@/lib/timeline/icons";
import type {
  TimelineEntryStatus,
  TimelineStepPosition,
} from "@/lib/timeline/types";

export interface RunStepProps {
  status: TimelineEntryStatus;
  position: TimelineStepPosition;
  /** The step kind's icon; a running or failed step shows its status. */
  icon?: IconFunctionComponent;
  title?: string | RichStr;
  /** Rendered at the inline end of the header, before the toggle. */
  headerAccessory?: React.ReactNode;
  /** The step's body; `null` for a step with nothing to show. */
  body?: React.ReactNode;
  /** Start open. */
  defaultExpanded?: boolean;
  /** Whether the step folds. Defaults to having a body. */
  expandable?: boolean;
  /** The body has no header (the body is its own control). */
  hideHeader?: boolean;
  isHover?: boolean;
  /** The surface when the step has not failed. */
  surfaceBackground?: TimelineSurfaceBackground;
}

function statusIcon(
  status: TimelineEntryStatus
): IconFunctionComponent | undefined {
  if (status === "streaming") return STEP_ICONS.running;
  // A stopped step must not look finished.
  if (status === "error" || status === "stopped") return STEP_ICONS.failed;
  return undefined;
}

/**
 * One step of a run, the same in chat and Craft: the status decides the icon
 * (spinner while running, alert when failed or stopped) and the failed tint.
 * Every step folds its body away completely; a failed step stays expandable
 * so its error is reachable.
 */
export function RunStep({
  status,
  position,
  icon,
  title,
  headerAccessory,
  body = null,
  defaultExpanded = false,
  expandable: expandableProp,
  hideHeader = false,
  isHover = false,
  surfaceBackground,
}: RunStepProps) {
  const [ownExpanded, setOwnExpanded] = useState(defaultExpanded);
  // A step without a header always shows its body.
  const isExpanded = hideHeader || ownExpanded;
  const failed = status === "error";
  const expandable = (expandableProp ?? body !== null) || failed;

  return (
    <StepContainer
      stepIcon={statusIcon(status) ?? icon}
      header={title}
      headerAccessory={headerAccessory}
      isExpanded={isExpanded}
      onToggle={() => setOwnExpanded((prev) => !prev)}
      supportsCollapsible={expandable}
      isFirstStep={position.isFirst}
      isLastStep={position.isLast}
      hideHeader={hideHeader}
      isHover={isHover}
      surfaceBackground={failed ? "error" : surfaceBackground}
    >
      {body}
    </StepContainer>
  );
}

export default RunStep;
