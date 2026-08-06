// Timeline expansion state (collapse + auto-collapse + parallel-tab sync). Port of web's
// useTimelineExpansion. userHasToggled is written/read only in callbacks/effects, never during
// render, to satisfy react-hooks/refs.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { TurnGroup } from "@/chat/timeline/transformers";

export interface TimelineExpansionState {
  isExpanded: boolean;
  handleToggle: () => void;
  parallelActiveTab: string;
  setParallelActiveTab: (tab: string) => void;
}

export function useTimelineExpansion(
  stopPacketSeen: boolean,
  lastTurnGroup: TurnGroup | undefined,
  hasDisplayContent: boolean = false,
): TimelineExpansionState {
  const [isExpanded, setIsExpanded] = useState(false);
  const [parallelActiveTab, setParallelActiveTab] = useState<string>("");
  const userHasToggled = useRef(false);

  const handleToggle = useCallback(() => {
    userHasToggled.current = true;
    setIsExpanded((prev) => !prev);
  }, []);

  // Auto-collapse on completion or when the answer starts, unless the user manually toggled.
  useEffect(() => {
    if ((stopPacketSeen || hasDisplayContent) && !userHasToggled.current) {
      setIsExpanded(false);
    }
  }, [stopPacketSeen, hasDisplayContent]);

  // Keep the active parallel tab valid. Adjusting state during render (not an effect) avoids
  // react-hooks/set-state-in-effect and converges in one pass.
  const validTabKeys = useMemo(
    () =>
      lastTurnGroup?.isParallel && lastTurnGroup.steps.length > 0
        ? lastTurnGroup.steps.map((s) => s.key)
        : null,
    [lastTurnGroup],
  );
  if (
    validTabKeys &&
    validTabKeys[0] &&
    !validTabKeys.includes(parallelActiveTab)
  ) {
    setParallelActiveTab(validTabKeys[0]);
  }

  return {
    isExpanded,
    handleToggle,
    parallelActiveTab,
    setParallelActiveTab,
  };
}
