"use client";

import React, { useState } from "react";
import { Line, type LineVariant } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { StepContainer } from "@/lib/timeline/components/StepContainer";
import { StreamingHeader } from "@/lib/timeline/components/headers/StreamingHeader";
import { TimelineRoot } from "@/lib/timeline/components/primitives/TimelineRoot";
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
  /** The title while the step runs, and after it fails or is stopped. */
  title?: string | RichStr;
  /** The title once the step is done. Defaults to `title`. */
  doneTitle?: string | RichStr;
  /** The title's identity: a new key swaps the title. Defaults to its text. */
  titleKey?: React.Key;
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
  /**
   * Draw the step as its own run card, outside any run: the card's header
   * is the step's title, and opening the card shows the step's body.
   */
  asCard?: boolean;
}

function statusIcon(
  status: TimelineEntryStatus
): IconFunctionComponent | undefined {
  if (status === "streaming") return STEP_ICONS.running;
  if (status === "error") return STEP_ICONS.failed;
  // A stopped step must not look finished.
  if (status === "stopped") return STEP_ICONS.stopped;
  return undefined;
}

function statusVariant(status: TimelineEntryStatus): LineVariant | undefined {
  if (status === "error") return "error-heavy";
  if (status === "stopped") return "error-light";
  return undefined;
}

/**
 * One step of a run, the same in chat and Craft. The status decides the icon
 * and the colour: a spinner while running; the alert icon and a red tint when
 * failed; a red stop icon when stopped. A step that did not finish keeps its
 * running title, and a done step shows `doneTitle`. Every step folds its body
 * away completely; a failed step stays expandable so its error is reachable.
 */
export function RunStep({
  status,
  position,
  icon,
  title,
  doneTitle,
  titleKey,
  headerAccessory,
  body = null,
  defaultExpanded = false,
  expandable: expandableProp,
  hideHeader = false,
  isHover = false,
  surfaceBackground,
  asCard = false,
}: RunStepProps) {
  const [ownExpanded, setOwnExpanded] = useState(defaultExpanded);
  const shownTitle = status === "done" ? (doneTitle ?? title) : title;

  if (asCard) {
    const running = status === "streaming";
    const foldable = body !== null;
    const cardBody = foldable
      ? {
          expandable: true as const,
          expanded: ownExpanded,
          expandedContent: (
            <div className="px-(--timeline-header-text-padding-x) pb-(--timeline-header-text-padding-y)">
              {body}
            </div>
          ),
        }
      : { expandable: false as const };
    return (
      <TimelineRoot>
        <Line
          flavour="card"
          filled={running || ownExpanded}
          onClick={foldable ? () => setOwnExpanded((prev) => !prev) : undefined}
          rightChildren={headerAccessory}
          {...cardBody}
        >
          {running ? (
            // A running step's title shimmers, as a run's working header does.
            <StreamingHeader
              headerText={
                typeof shownTitle === "string"
                  ? shownTitle
                  : (shownTitle?.raw ?? "")
              }
            />
          ) : (
            <Section
              flexDirection="row"
              justifyContent="start"
              gap={0}
              height="fit"
              className="flex-1 min-w-0 mx-(--timeline-header-text-padding-x) my-(--timeline-header-text-padding-y)"
            >
              <Content
                font="main-ui-action"
                icon={statusIcon(status) ?? icon}
                title={shownTitle ?? ""}
                titleColor="text-03"
              />
            </Section>
          )}
        </Line>
      </TimelineRoot>
    );
  }
  // A step without a header always shows its body.
  const isExpanded = hideHeader || ownExpanded;
  const failed = status === "error";
  const expandable = (expandableProp ?? body !== null) || failed;

  return (
    <StepContainer
      stepIcon={statusIcon(status) ?? icon}
      header={shownTitle}
      headerKey={titleKey}
      headerAccessory={headerAccessory}
      isExpanded={isExpanded}
      onToggle={() => setOwnExpanded((prev) => !prev)}
      supportsCollapsible={expandable}
      isFirstStep={position.isFirst}
      isLastStep={position.isLast}
      hideHeader={hideHeader}
      isHover={isHover}
      surfaceBackground={surfaceBackground}
      variant={statusVariant(status)}
    >
      {body}
    </StepContainer>
  );
}

export default RunStep;
