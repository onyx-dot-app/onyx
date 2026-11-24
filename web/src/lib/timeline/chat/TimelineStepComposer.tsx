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
  /** Whether RunStep should show collapse controls. */
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
            icon={result.icon as IconFunctionComponent | undefined}
            title={result.status ?? undefined}
            doneTitle={result.doneStatus ?? undefined}
            titleKey={result.statusKey}
            defaultExpanded={result.isExpanded}
            body={result.content}
          />
        )
      )}
    </>
  );
}

export default TimelineStepComposer;
