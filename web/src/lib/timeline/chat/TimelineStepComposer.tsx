import React from "react";
import type { IconFunctionComponent } from "@opal/types";
import { RunStep } from "@/lib/timeline/components/RunStep";
import type { TimelineEntryStatus } from "@/lib/timeline/types";
import { TimelineRendererOutput } from "./TimelineRendererComponent";

export interface TimelineStepComposerProps {
  /** Results produced by the active renderer. */
  results: TimelineRendererOutput;
  /** The step's status; it decides the first row's icon and failed tint. */
  status?: TimelineEntryStatus;
  /** Shown at the end of the first row's header, e.g. a memory's tag. */
  headerAccessory?: React.ReactNode;
  /** The step's key: its rows keep their open state in the run card. */
  stepId?: string;
}

/**
 * TimelineStepComposer renders renderer results into either raw content blocks
 * or shared run steps (`RunStep`), based on the layout contract.
 */
export function TimelineStepComposer({
  results,
  status = "done",
  headerAccessory,
  stepId,
}: TimelineStepComposerProps) {
  return (
    <>
      {results.map((result, index) =>
        result.timelineLayout === "content" ? (
          <React.Fragment key={index}>{result.content}</React.Fragment>
        ) : (
          <RunStep
            key={index}
            id={stepId === undefined ? undefined : `${stepId}:${index}`}
            status={index === 0 ? status : "done"}
            icon={result.icon as IconFunctionComponent | undefined}
            title={result.status ?? undefined}
            doneTitle={result.doneStatus ?? undefined}
            titleKey={result.statusKey}
            defaultExpanded={result.isExpanded}
            body={result.content}
            headerAccessory={index === 0 ? headerAccessory : undefined}
          />
        )
      )}
    </>
  );
}

export default TimelineStepComposer;
