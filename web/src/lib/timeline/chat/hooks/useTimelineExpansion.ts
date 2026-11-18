import { useState, useCallback } from "react";
import { TurnGroup } from "../transformers";

export interface TimelineExpansionState {
  isExpanded: boolean;
  handleToggle: () => void;
  parallelActiveTab: string;
  setParallelActiveTab: (tab: string) => void;
}

/**
 * Manages expansion state for the timeline.
 * The timeline starts collapsed and only the user expands it. A parallel turn
 * group without the active tab selects its first step.
 */
export function useTimelineExpansion(
  lastTurnGroup: TurnGroup | undefined
): TimelineExpansionState {
  const [isExpanded, setIsExpanded] = useState(false);
  const [parallelActiveTab, setParallelActiveTab] = useState<string>("");
  const handleToggle = useCallback(() => {
    setIsExpanded((prev) => !prev);
  }, []);

  // A new parallel turn group without the active tab selects its first step.
  const firstParallelStep = lastTurnGroup?.isParallel
    ? lastTurnGroup.steps[0]
    : undefined;
  if (
    firstParallelStep &&
    !lastTurnGroup?.steps.some((step) => step.key === parallelActiveTab)
  ) {
    setParallelActiveTab(firstParallelStep.key);
  }

  return {
    isExpanded,
    handleToggle,
    parallelActiveTab,
    setParallelActiveTab,
  };
}
