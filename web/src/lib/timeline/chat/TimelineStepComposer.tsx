import React from "react";
import type { IconFunctionComponent } from "@opal/types";
import { RunStep } from "@/lib/timeline/components/RunStep";
import type { TimelineEntryStatus } from "@/lib/timeline/types";
import { TimelineRendererOutput } from "./TimelineRendererComponent";

export interface TimelineStepComposerProps {
  /** Results produced by the active renderer. */
  results: TimelineRendererOutput;
  /** Whether the overall step is the last in the timeline (affects connector). */
  isLastStep: boolean;
  /** Whether the overall step is the first in the timeline (affects connector). */
  isFirstStep: boolean;
  /** Whether StepContainer should show collapse controls. */
  collapsible?: boolean;
  /** The step's status; it decides the first row's icon and failed tint. */
  status?: TimelineEntryStatus;
}

/**
 * TimelineStepComposer renders renderer results into either raw content blocks
 * or shared run steps (`RunStep`), based on the layout contract.
 */
export function TimelineStepComposer({
  results,
  isLastStep,
  isFirstStep,
  collapsible = true,
  status = "done",
}: TimelineStepComposerProps) {
  return (
    <>
      {results.map((result, index) =>
        result.timelineLayout === "content" ? (
          <React.Fragment key={index}>{result.content}</React.Fragment>
        ) : (
          <RunStep
            key={index}
            status={index === 0 ? status : "done"}
            position={{
              isFirst: index === 0 && isFirstStep,
              isLast: index === results.length - 1 && isLastStep,
            }}
            icon={result.icon as IconFunctionComponent | undefined}
            title={result.status ?? undefined}
            defaultExpanded={result.isExpanded}
            expandable={collapsible}
            isHover={result.isHover}
            surfaceBackground={result.surfaceBackground}
            body={result.content}
          />
        )
      )}
    </>
  );
}

export default TimelineStepComposer;
