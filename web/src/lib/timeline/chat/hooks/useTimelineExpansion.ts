import { useState, useEffect, useCallback, useRef } from "react";

export interface TimelineExpansionState {
  isExpanded: boolean;
  handleToggle: () => void;
}

/**
 * Manages expansion state for the timeline.
 * Auto-collapses when streaming completes or message content starts.
 */
export function useTimelineExpansion(
  stopPacketSeen: boolean,
  hasDisplayContent: boolean = false
): TimelineExpansionState {
  const [isExpanded, setIsExpanded] = useState(false);
  const userHasToggled = useRef(false);

  const handleToggle = useCallback(() => {
    userHasToggled.current = true;
    setIsExpanded((prev) => !prev);
  }, []);

  // Auto-collapse when streaming completes or message content starts
  // BUT respect user intent - if they've manually toggled, don't auto-collapse
  useEffect(() => {
    if ((stopPacketSeen || hasDisplayContent) && !userHasToggled.current) {
      setIsExpanded(false);
    }
  }, [stopPacketSeen, hasDisplayContent]);

  return {
    isExpanded,
    handleToggle,
  };
}
