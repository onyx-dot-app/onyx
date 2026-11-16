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
  /** Accessible name of the toggle. */
  toggleLabel?: string;
  /** The step's body; `null` for a step with nothing to show. */
  body?: React.ReactNode;
  /** Start open. Ignored when `isExpanded` controls the step. */
  defaultExpanded?: boolean;
  /**
   * Controlled open state, for a step whose body changes rather than hides
   * when folded. Uncontrolled steps fold their body away, animated.
   */
  isExpanded?: boolean;
  onToggle?: () => void;
  /** Shown on the toggle while folded, in place of the expand icon. */
  collapsedIcon?: IconFunctionComponent;
  /** Whether the step folds. Defaults to having a body. */
  expandable?: boolean;
  /** The body has no header (the body is its own control). */
  hideHeader?: boolean;
  noPaddingRight?: boolean;
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
 * A failed step stays expandable so its error is reachable.
 */
export function RunStep({
  status,
  position,
  icon,
  title,
  headerAccessory,
  toggleLabel,
  body = null,
  defaultExpanded = false,
  isExpanded: controlledExpanded,
  onToggle,
  collapsedIcon,
  expandable: expandableProp,
  hideHeader = false,
  noPaddingRight = false,
  isHover = false,
  surfaceBackground,
}: RunStepProps) {
  const [ownExpanded, setOwnExpanded] = useState(defaultExpanded);
  const isControlled = controlledExpanded !== undefined;
  // A step without a header always shows its body.
  const isExpanded =
    hideHeader || (isControlled ? controlledExpanded : ownExpanded);
  const failed = status === "error";
  const expandable = (expandableProp ?? body !== null) || failed;

  return (
    <StepContainer
      stepIcon={statusIcon(status) ?? icon}
      header={title}
      headerAccessory={headerAccessory}
      toggleLabel={toggleLabel}
      isExpanded={isExpanded}
      onToggle={isControlled ? onToggle : () => setOwnExpanded((prev) => !prev)}
      supportsCollapsible={expandable}
      collapsedIcon={collapsedIcon}
      isFirstStep={position.isFirst}
      isLastStep={position.isLast}
      hideHeader={hideHeader}
      noPaddingRight={noPaddingRight}
      isHover={isHover}
      surfaceBackground={failed ? "error" : surfaceBackground}
      foldBody={!isControlled}
    >
      {body}
    </StepContainer>
  );
}

export default RunStep;
