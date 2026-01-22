import { useState, useEffect, useCallback } from "react";
import { TurnGroup } from "../transformers";

export interface TimelineExpansionState {
  isExpanded: boolean;
  handleToggle: () => void;
  parallelActiveTab: string;
  setParallelActiveTab: (tab: string) => void;
}

/**
 * Manages expansion state for the timeline.
 * Auto-collapses when streaming completes or message content starts, and syncs parallel tab selection.
 */
export function useTimelineExpansion(
  stopPacketSeen: boolean,
  lastTurnGroup: TurnGroup | undefined,
  hasDisplayContent: boolean = false
): TimelineExpansionState {
  const [isExpanded, setIsExpanded] = useState(false);
  const [parallelActiveTab, setParallelActiveTab] = useState<string>("");

  const handleToggle = useCallback(() => {
    setIsExpanded((prev) => !prev);
  }, []);

  // Auto-collapse when streaming completes or message content starts
  useEffect(() => {
    if (stopPacketSeen || hasDisplayContent) {
      setIsExpanded(false);
    }
  }, [stopPacketSeen, hasDisplayContent]);

  // Sync active tab when parallel turn group changes
  useEffect(() => {
    if (lastTurnGroup?.isParallel && lastTurnGroup.steps.length > 0) {
      const validTabs = lastTurnGroup.steps.map((s) => s.key);
      const firstStep = lastTurnGroup.steps[0];
      if (firstStep && !validTabs.includes(parallelActiveTab)) {
        setParallelActiveTab(firstStep.key);
      }
    }
  }, [lastTurnGroup, parallelActiveTab]);

  return {
    isExpanded,
    handleToggle,
    parallelActiveTab,
    setParallelActiveTab,
  };
}
