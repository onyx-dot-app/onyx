import React, { FunctionComponent } from "react";
import { IconProps } from "@opal/types";
import { StepContainer } from "./StepContainer";
import {
  TimelineRendererOutput,
  TimelineRendererResult,
} from "./TimelineRendererComponent";

export interface TimelineStepComposerProps {
  /** Results produced by the active renderer. */
  results: TimelineRendererOutput;
  /** Whether the overall step is the last in the timeline (affects connector). */
  isLastStep: boolean;
  /** Whether the overall step is the first in the timeline (affects connector). */
  isFirstStep: boolean;
  /** Whether the timeline has a single step (used to hide headers). */
  isSingleStep?: boolean;
  /** Whether StepContainer should show collapse controls. */
  collapsible?: boolean;
  /** Remove right padding for long-form content (reasoning, deep research). */
  noPaddingRight?: boolean;
  /** Optional resolver for custom collapsed icon per result. */
  getCollapsedIcon?: (
    result: TimelineRendererResult
  ) => FunctionComponent<IconProps> | undefined;
}

/**
 * TimelineStepComposer renders renderer results into either raw content blocks
 * or StepContainer-wrapped timeline rows based on the layout contract.
 */
export function TimelineStepComposer({
  results,
  isLastStep,
  isFirstStep,
  isSingleStep = false,
  collapsible = true,
  noPaddingRight = false,
  getCollapsedIcon,
}: TimelineStepComposerProps) {
  return (
    <>
      {results.map((result, index) =>
        result.timelineLayout === "content" ? (
          <React.Fragment key={index}>{result.content}</React.Fragment>
        ) : (
          <StepContainer
            key={index}
            stepIcon={result.icon as FunctionComponent<IconProps> | undefined}
            header={result.status}
            isExpanded={result.isExpanded}
            onToggle={result.onToggle}
            collapsible={collapsible}
            supportsCollapsible={result.supportsCollapsible}
            isLastStep={index === results.length - 1 && isLastStep}
            isFirstStep={index === 0 && isFirstStep}
            hideHeader={
              results.length === 1 &&
              isSingleStep &&
              !result.supportsCollapsible
            }
            collapsedIcon={
              getCollapsedIcon ? getCollapsedIcon(result) : undefined
            }
            noPaddingRight={noPaddingRight}
            isHover={result.isHover}
          >
            {result.content}
          </StepContainer>
        )
      )}
    </>
  );
}

export default TimelineStepComposer;
