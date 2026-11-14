import { useState, useEffect, useCallback, useRef } from "react";

export interface TimelineExpansionState {
  isExpanded: boolean;
  handleToggle: () => void;
}

/**
 * Manages expansion state for the timeline, as Craft does: a run is open
 * while it works and folds once message content follows it. A settled run
 * starts folded. A manual toggle stops the automatic fold.
 */
export function useTimelineExpansion(
  stopPacketSeen: boolean,
  hasDisplayContent: boolean = false
): TimelineExpansionState {
  const [isExpanded, setIsExpanded] = useState(
    () => !stopPacketSeen && !hasDisplayContent
  );
  const userHasToggled = useRef(false);

  const handleToggle = useCallback(() => {
    userHasToggled.current = true;
    setIsExpanded((prev) => !prev);
  }, []);

  useEffect(() => {
    if (hasDisplayContent && !userHasToggled.current) {
      setIsExpanded(false);
    }
  }, [hasDisplayContent]);

  return {
    isExpanded,
    handleToggle,
  };
}
