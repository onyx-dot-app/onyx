/* eslint-disable react-hooks/set-state-in-effect -- auto-collapse/active-tab sync intentionally set state in effects; ported verbatim from web. */
import { useState, useEffect, useCallback, useRef } from "react";
import { TurnGroup } from "@/state/timeline/transformers";

export interface TimelineExpansionState {
  isExpanded: boolean;
  handleToggle: () => void;
  parallelActiveTab: string;
  setParallelActiveTab: (tab: string) => void;
}

export function useTimelineExpansion(
  stopPacketSeen: boolean,
  lastTurnGroup: TurnGroup | undefined,
  hasDisplayContent: boolean = false
): TimelineExpansionState {
  const [isExpanded, setIsExpanded] = useState(false);
  const [parallelActiveTab, setParallelActiveTab] = useState<string>("");
  const userHasToggled = useRef(false);

  const handleToggle = useCallback(() => {
    userHasToggled.current = true;
    setIsExpanded((prev) => !prev);
  }, []);

  // Auto-collapse on completion/display content, unless the user toggled manually.
  useEffect(() => {
    if ((stopPacketSeen || hasDisplayContent) && !userHasToggled.current) {
      setIsExpanded(false);
    }
  }, [stopPacketSeen, hasDisplayContent]);

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
