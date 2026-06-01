// TimelineStepComposer.tsx — renders renderer results into raw content
// (timelineLayout "content") or StepContainer-wrapped rows.
// Native mirror of web TimelineStepComposer.

import { Fragment } from "react";

import { StepContainer } from "@/components/message/timeline/StepContainer";
import type { TimelineRendererOutput } from "@/components/message/timeline/TimelineRendererComponent";

export interface TimelineStepComposerProps {
  results: TimelineRendererOutput;
  isLastStep: boolean;
  isFirstStep: boolean;
  isSingleStep?: boolean;
  collapsible?: boolean;
}

export function TimelineStepComposer({
  results,
  isLastStep,
  isFirstStep,
  isSingleStep = false,
  collapsible = true,
}: TimelineStepComposerProps) {
  return (
    <>
      {results.map((result, index) =>
        result.timelineLayout === "content" ? (
          <Fragment key={index}>{result.content}</Fragment>
        ) : (
          <StepContainer
            key={index}
            stepIconName={result.icon}
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
              results.length === 1 && isSingleStep && !result.supportsCollapsible
            }
            noPaddingRight={result.noPaddingRight ?? false}
            surfaceBackground={result.surfaceBackground}
          >
            {result.content}
          </StepContainer>
        )
      )}
    </>
  );
}

export default TimelineStepComposer;
