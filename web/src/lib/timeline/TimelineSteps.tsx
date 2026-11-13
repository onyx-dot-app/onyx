import React from "react";
import type {
  TimelineEntry,
  TimelineGroup,
  TimelineStepPosition,
} from "@/lib/timeline/types";

export interface TimelineStepsProps<P> {
  groups: readonly TimelineGroup<P>[];
  /** Renders one entry as a rail step. */
  renderEntry: (
    entry: TimelineEntry<P>,
    position: TimelineStepPosition
  ) => React.ReactNode;
  /** Groups that render as one tabbed block instead of one step per entry. */
  isTabbedGroup?: (group: TimelineGroup<P>) => boolean;
  /** Renders a tabbed group. Required when `isTabbedGroup` can return true. */
  renderTabbedGroup?: (
    group: TimelineGroup<P>,
    position: TimelineStepPosition
  ) => React.ReactNode;
}

/**
 * TimelineSteps lays out timeline groups in order. Rows are keyed by entry id,
 * so a step that moves keeps its state.
 */
export function TimelineSteps<P>({
  groups,
  renderEntry,
  isTabbedGroup,
  renderTabbedGroup,
}: TimelineStepsProps<P>) {
  return (
    <>
      {groups.flatMap((group, groupIndex) => {
        const isFirstGroup = groupIndex === 0;
        const isLastGroup = groupIndex === groups.length - 1;

        if (renderTabbedGroup && isTabbedGroup?.(group)) {
          return (
            <React.Fragment key={group.entries[0]?.id ?? group.id}>
              {renderTabbedGroup(group, {
                isFirst: isFirstGroup,
                isLast: isLastGroup,
              })}
            </React.Fragment>
          );
        }

        return group.entries.map((entry, entryIndex) => (
          <React.Fragment key={entry.id}>
            {renderEntry(entry, {
              isFirst: isFirstGroup && entryIndex === 0,
              isLast: isLastGroup && entryIndex === group.entries.length - 1,
            })}
          </React.Fragment>
        ));
      })}
    </>
  );
}

export default TimelineSteps;
