import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { TurnGroup } from "../transformers";
import { isCodingAgentPackets } from "../packetHelpers";

export interface TimelineExpansionState {
  isExpanded: boolean;
  handleToggle: () => void;
  parallelActiveTab: string;
  setParallelActiveTab: (tab: string) => void;
}

/**
 * Manages expansion state for the timeline.
 * Auto-collapses when streaming completes or message content starts, and syncs parallel tab selection.
 *
 * Note: coding-agent detection scans *all* turn groups, not just the last —
 * the agent's final-answer streams as a separate MESSAGE_DELTA group at
 * turn_index + 1, so the last group is typically the chat bubble, not the
 * agent. Auto-collapse keying off only the last group would dismiss the
 * agent's timeline as soon as the first answer token arrives.
 */
export function useTimelineExpansion(
  stopPacketSeen: boolean,
  turnGroups: TurnGroup[],
  hasDisplayContent: boolean = false
): TimelineExpansionState {
  const containsCodingAgent = useMemo(
    () =>
      turnGroups.some((group) =>
        group.steps.some((step) => isCodingAgentPackets(step.packets))
      ),
    [turnGroups]
  );

  const lastTurnGroup =
    turnGroups.length > 0 ? turnGroups[turnGroups.length - 1] : undefined;

  const [isExpanded, setIsExpanded] = useState(containsCodingAgent);
  const [parallelActiveTab, setParallelActiveTab] = useState<string>("");
  const userHasToggled = useRef(false);

  const handleToggle = useCallback(() => {
    userHasToggled.current = true;
    setIsExpanded((prev) => !prev);
  }, []);

  // Default to expanded as soon as a coding-agent group appears anywhere in
  // the timeline.
  useEffect(() => {
    if (containsCodingAgent && !userHasToggled.current) {
      setIsExpanded(true);
    }
  }, [containsCodingAgent]);

  // Auto-collapse when streaming completes or message content starts
  // BUT respect user intent - if they've manually toggled, don't auto-collapse.
  // Skip auto-collapse when any group is a coding-agent so the tab UI stays
  // visible alongside the streaming chat answer.
  useEffect(() => {
    if (
      (stopPacketSeen || hasDisplayContent) &&
      !userHasToggled.current &&
      !containsCodingAgent
    ) {
      setIsExpanded(false);
    }
  }, [stopPacketSeen, hasDisplayContent, containsCodingAgent]);

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
