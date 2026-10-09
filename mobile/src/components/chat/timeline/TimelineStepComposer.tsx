import { Fragment } from "react";

import type { TimelineRendererResult } from "@/components/chat/renderers/timelineContract";
import type { IconFunctionComponent } from "@/icons/types";

import { StepContainer } from "./StepContainer";

export interface TimelineStepComposerProps {
  results: TimelineRendererResult[];
  // Drive the rail connectors.
  isLastStep: boolean;
  isFirstStep: boolean;
  // A lone step hides its header, so the body reads as the timeline's only content.
  isSingleStep?: boolean;
  collapsible?: boolean;
  getCollapsedIcon?: (
    result: TimelineRendererResult,
  ) => IconFunctionComponent | undefined;
}

export function TimelineStepComposer({
  results,
  isLastStep,
  isFirstStep,
  isSingleStep = false,
  collapsible = true,
  getCollapsedIcon,
}: TimelineStepComposerProps) {
  return (
    <>
      {results.map((result, index) =>
        result.timelineLayout === "content" ? (
          <Fragment key={index}>{result.content}</Fragment>
        ) : (
          <StepContainer
            key={index}
            stepIcon={result.icon ?? undefined}
            header={result.status}
            isExpanded={result.isExpanded}
            onToggle={result.onToggle}
            collapsible={
              collapsible && (!isSingleStep || !!result.alwaysCollapsible)
            }
            supportsCollapsible={result.supportsCollapsible}
            isLastStep={index === results.length - 1 && isLastStep}
            isFirstStep={index === 0 && isFirstStep}
            hideHeader={
              results.length === 1 &&
              isSingleStep &&
              !result.supportsCollapsible
            }
            collapsedIcon={getCollapsedIcon?.(result)}
            noPaddingRight={result.noPaddingRight ?? false}
            surfaceBackground={result.surfaceBackground}
          >
            {result.content}
          </StepContainer>
        ),
      )}
    </>
  );
}

export default TimelineStepComposer;
