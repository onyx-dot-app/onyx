import { Packet } from "@/app/chat/services/streamingModels";
import { useMemo, useState, useCallback, useEffect } from "react";
import { useRef } from "react";
import { getToolKey, parseToolKey } from "../toolDisplayHelpers";

function getInitialTools(
  toolGroups: { turn_index: number; tab_index: number; packets: Packet[] }[],
  isComplete: boolean
): Set<string> {
  if (isComplete) {
    return new Set(
      toolGroups.map((group) => getToolKey(group.turn_index, group.tab_index))
    );
  }
  return new Set();
}

export function useToolDisplayTiming(
  toolGroups: { turn_index: number; tab_index: number; packets: Packet[] }[],
  isFinalAnswerComing: boolean,
  isComplete: boolean,
  expectedBranchesPerTurn?: Map<number, number>
) {
  /* Adds a "minimum display time" for each tool and makes sure that we 
  display tools one after another (e.g. only after the rendering of a tool is complete,
  do we start showing the next tool). 
  
  For parallel tools (same turn_index, different tab_index), they are shown together.
  When expectedBranchesPerTurn is provided, we wait for all expected branches before
  considering a turn complete. */
  const MINIMUM_DISPLAY_TIME_MS = 1500; // 1.5 seconds minimum display time
  const [visibleTools, setVisibleTools] = useState<Set<string>>(() =>
    getInitialTools(toolGroups, isComplete)
  );
  const [completedToolInds, setCompletedToolInds] = useState<Set<string>>(() =>
    // if the final answer is already coming, then we can just assume all tools
    // are complete. This happens when you switch back into a mid-stream chat.
    isFinalAnswerComing
      ? new Set(
          toolGroups.map((group) =>
            getToolKey(group.turn_index, group.tab_index)
          )
        )
      : getInitialTools(toolGroups, isComplete)
  );

  // Track when each tool (by turn_index) starts displaying
  // For parallel tools, we track by turn_index since they start together
  const toolStartTimesRef = useRef<Map<number, number>>(new Map());

  // Track pending completions that are waiting for minimum display time
  const pendingOrFullCompletionsRef = useRef<
    Map<string, NodeJS.Timeout | null>
  >(new Map());

  // Group tools by turn_index for parallel tool handling
  const toolsByTurnIndex = useMemo(() => {
    const grouped = new Map<
      number,
      { turn_index: number; tab_index: number; packets: Packet[] }[]
    >();
    toolGroups.forEach((group) => {
      const existing = grouped.get(group.turn_index) || [];
      existing.push(group);
      grouped.set(group.turn_index, existing);
    });
    return grouped;
  }, [toolGroups]);

  // Get unique turn indices in order
  const turnIndicesInOrder = useMemo(() => {
    const seen = new Set<number>();
    const result: number[] = [];
    toolGroups.forEach((group) => {
      if (!seen.has(group.turn_index)) {
        seen.add(group.turn_index);
        result.push(group.turn_index);
      }
    });
    return result;
  }, [toolGroups]);

  // Effect to manage which tools are visible based on completed tools
  useEffect(() => {
    if (toolGroups.length === 0) return;

    // Get the first turn_index and make all its tools visible
    if (visibleTools.size === 0 && turnIndicesInOrder[0] !== undefined) {
      const firstTurnIndex = turnIndicesInOrder[0];
      const toolsInFirstTurn = toolsByTurnIndex.get(firstTurnIndex) || [];
      const newVisible = new Set<string>();
      toolsInFirstTurn.forEach((tool) => {
        newVisible.add(getToolKey(tool.turn_index, tool.tab_index));
      });
      setVisibleTools(newVisible);
      toolStartTimesRef.current.set(firstTurnIndex, Date.now());
      return;
    }

    // Find the current visible turn_index
    const visibleTurnIndices = new Set<number>();
    visibleTools.forEach((key) => {
      const { turn_index } = parseToolKey(key);
      visibleTurnIndices.add(turn_index);
    });

    // Check if there are any NEW parallel tools that arrived for already-visible turns
    // This handles the case where parallel tools stream in one after another
    let hasNewParallelTools = false;
    visibleTurnIndices.forEach((turnIndex) => {
      const toolsInTurn = toolsByTurnIndex.get(turnIndex) || [];
      toolsInTurn.forEach((tool) => {
        const toolKey = getToolKey(tool.turn_index, tool.tab_index);
        if (!visibleTools.has(toolKey)) {
          hasNewParallelTools = true;
        }
      });
    });

    if (hasNewParallelTools) {
      setVisibleTools((prev) => {
        const newSet = new Set(prev);
        visibleTurnIndices.forEach((turnIndex) => {
          const toolsInTurn = toolsByTurnIndex.get(turnIndex) || [];
          toolsInTurn.forEach((tool) => {
            newSet.add(getToolKey(tool.turn_index, tool.tab_index));
          });
        });
        return newSet;
      });
      return;
    }

    // Find the last visible turn_index
    const lastVisibleTurnIndex = Math.max(...Array.from(visibleTurnIndices));
    const lastVisibleTurnIndexPosition =
      turnIndicesInOrder.indexOf(lastVisibleTurnIndex);

    // Check if all tools in the last visible turn are completed
    const toolsInLastTurn = toolsByTurnIndex.get(lastVisibleTurnIndex) || [];
    const expectedBranchCount =
      expectedBranchesPerTurn?.get(lastVisibleTurnIndex) ?? 0;

    // If we expect more branches than we have, this turn is not complete
    const hasAllExpectedBranches =
      expectedBranchCount === 0 ||
      toolsInLastTurn.length >= expectedBranchCount;

    const allToolsInLastTurnCompleted =
      hasAllExpectedBranches &&
      toolsInLastTurn.every((tool) =>
        completedToolInds.has(getToolKey(tool.turn_index, tool.tab_index))
      );

    // If all tools in the last turn are completed and there are more turns, show the next turn
    if (
      allToolsInLastTurnCompleted &&
      lastVisibleTurnIndexPosition < turnIndicesInOrder.length - 1
    ) {
      const nextTurnIndex =
        turnIndicesInOrder[lastVisibleTurnIndexPosition + 1];
      if (nextTurnIndex !== undefined) {
        const toolsInNextTurn = toolsByTurnIndex.get(nextTurnIndex) || [];

        setVisibleTools((prev) => {
          const newSet = new Set(prev);
          toolsInNextTurn.forEach((tool) => {
            newSet.add(getToolKey(tool.turn_index, tool.tab_index));
          });
          return newSet;
        });
        toolStartTimesRef.current.set(nextTurnIndex, Date.now());
      }
    }
  }, [
    toolGroups,
    completedToolInds,
    visibleTools,
    toolsByTurnIndex,
    turnIndicesInOrder,
    expectedBranchesPerTurn,
  ]);

  // Callback to handle when a tool completes
  const handleToolComplete = useCallback(
    (turnIndex: number, tabIndex: number = 0) => {
      const toolKey = getToolKey(turnIndex, tabIndex);
      if (
        completedToolInds.has(toolKey) ||
        pendingOrFullCompletionsRef.current.has(toolKey)
      ) {
        return;
      }

      const now = Date.now();
      const startTime = toolStartTimesRef.current.get(turnIndex);

      // If we don't have a start time, record it now (tool just started)
      if (!startTime) {
        toolStartTimesRef.current.set(turnIndex, now);
      }

      const actualStartTime = toolStartTimesRef.current.get(turnIndex) || now;
      const elapsedTime = now - actualStartTime;

      if (elapsedTime >= MINIMUM_DISPLAY_TIME_MS) {
        // Enough time has passed, mark as complete immediately
        setCompletedToolInds((prev) => new Set(prev).add(toolKey));
        pendingOrFullCompletionsRef.current.set(toolKey, null);
      } else {
        // Not enough time has passed, delay the completion
        const remainingTime = MINIMUM_DISPLAY_TIME_MS - elapsedTime;

        // Clear any existing timeout for this tool
        const existingTimeout =
          pendingOrFullCompletionsRef.current.get(toolKey);
        if (existingTimeout) {
          clearTimeout(existingTimeout);
        }

        // Set a timeout to mark as complete after the remaining time
        const timeoutId = setTimeout(() => {
          setCompletedToolInds((prev) => new Set(prev).add(toolKey));
          pendingOrFullCompletionsRef.current.set(toolKey, null);
        }, remainingTime);

        pendingOrFullCompletionsRef.current.set(toolKey, timeoutId);
      }
    },
    []
  );

  // Clean up timeouts on unmount
  useEffect(() => {
    return () => {
      pendingOrFullCompletionsRef.current.forEach((timeout) => {
        if (timeout) {
          clearTimeout(timeout);
        }
      });
    };
  }, []);

  // Check if all tools are displayed (visible and completed)
  // Note: We intentionally do NOT require isFinalAnswerComing here to avoid a circular dependency.
  // The parent component (AIMessage) relies on onAllToolsDisplayed callback to set finalAnswerComing,
  // so requiring it here would create a deadlock where tools never report completion.
  const allToolsDisplayed = useMemo(() => {
    if (toolGroups.length === 0) return true;

    // All tools are displayed if they're all visible and completed
    const allVisible = toolGroups.every((group) =>
      visibleTools.has(getToolKey(group.turn_index, group.tab_index))
    );
    const allCompleted = toolGroups.every((group) =>
      completedToolInds.has(getToolKey(group.turn_index, group.tab_index))
    );

    // Also check that we have all expected branches for each turn
    let hasAllExpectedBranches = true;
    if (expectedBranchesPerTurn) {
      expectedBranchesPerTurn.forEach((expectedCount, turnIndex) => {
        const toolsInTurn = toolsByTurnIndex.get(turnIndex) || [];
        if (toolsInTurn.length < expectedCount) {
          hasAllExpectedBranches = false;
        }
      });
    }

    return allVisible && allCompleted && hasAllExpectedBranches;
  }, [
    toolGroups,
    visibleTools,
    completedToolInds,
    expectedBranchesPerTurn,
    toolsByTurnIndex,
  ]);

  return {
    visibleTools,
    handleToolComplete,
    allToolsDisplayed,
  };
}
