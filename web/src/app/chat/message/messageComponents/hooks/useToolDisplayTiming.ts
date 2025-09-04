import { Packet } from "@/app/chat/services/streamingModels";
import { useMemo, useState, useCallback, useEffect } from "react";
import { useRef } from "react";

function getInitialTools(
  toolGroups: { ind: number; packets: Packet[] }[],
  isComplete: boolean
): Set<number> {
  if (isComplete) {
    return new Set(toolGroups.map((group) => group.ind));
  }
  return new Set();
}

export function useToolDisplayTiming(
  toolGroups: { ind: number; packets: Packet[] }[],
  isFinalAnswerComing: boolean,
  isComplete: boolean
) {
  /* Adds a "minimum display time" for each tool and makes sure that we 
  display tools one after another (e.g. only after the rendering of a tool is complete,
  do we start showing the next tool). */
  const MINIMUM_DISPLAY_TIME_MS = 1500; // 1.5 seconds minimum display time
  const [visibleTools, setVisibleTools] = useState<Set<number>>(() =>
    getInitialTools(toolGroups, isComplete)
  );
  const [completedToolInds, setCompletedToolInds] = useState<Set<number>>(() =>
    getInitialTools(toolGroups, isComplete)
  );

  // Track when each tool starts displaying
  const toolStartTimesRef = useRef<Map<number, number>>(new Map());

  // Track pending completions that are waiting for minimum display time
  const pendingOrFullCompletionsRef = useRef<
    Map<number, NodeJS.Timeout | null>
  >(new Map());

  // Effect to manage which tools are visible based on completed tools
  useEffect(() => {
    if (toolGroups.length === 0) return;

    // First tool is always visible
    if (visibleTools.size === 0 && toolGroups[0]) {
      setVisibleTools(new Set([toolGroups[0].ind]));
      toolStartTimesRef.current.set(toolGroups[0].ind, Date.now());
      return;
    }

    // Find the next tool to show
    const visibleToolsArray = Array.from(visibleTools);
    const lastVisibleToolIndex = toolGroups.findIndex(
      (group) => group.ind === visibleToolsArray[visibleToolsArray.length - 1]
    );

    // Check if the last visible tool is completed
    const lastVisibleToolInd = toolGroups[lastVisibleToolIndex]?.ind;
    if (
      lastVisibleToolInd !== undefined &&
      completedToolInds.has(lastVisibleToolInd) &&
      lastVisibleToolIndex < toolGroups.length - 1
    ) {
      // Show the next tool
      const nextTool = toolGroups[lastVisibleToolIndex + 1];
      if (nextTool) {
        setVisibleTools((prev) => new Set(prev).add(nextTool.ind));
        toolStartTimesRef.current.set(nextTool.ind, Date.now());
      }
    }
  }, [toolGroups, completedToolInds, visibleTools.size]);

  // Callback to handle when a tool completes
  const handleToolComplete = useCallback((toolInd: number) => {
    if (
      completedToolInds.has(toolInd) ||
      pendingOrFullCompletionsRef.current.has(toolInd)
    ) {
      return;
    }

    const now = Date.now();
    const startTime = toolStartTimesRef.current.get(toolInd);

    // If we don't have a start time, record it now (tool just started)
    if (!startTime) {
      toolStartTimesRef.current.set(toolInd, now);
    }

    const actualStartTime = toolStartTimesRef.current.get(toolInd) || now;
    const elapsedTime = now - actualStartTime;

    if (elapsedTime >= MINIMUM_DISPLAY_TIME_MS) {
      // Enough time has passed, mark as complete immediately
      setCompletedToolInds((prev) => new Set(prev).add(toolInd));
      pendingOrFullCompletionsRef.current.set(toolInd, null);
    } else {
      // Not enough time has passed, delay the completion
      const remainingTime = MINIMUM_DISPLAY_TIME_MS - elapsedTime;

      // Clear any existing timeout for this tool
      const existingTimeout = pendingOrFullCompletionsRef.current.get(toolInd);
      if (existingTimeout) {
        clearTimeout(existingTimeout);
      }

      // Set a timeout to mark as complete after the remaining time
      const timeoutId = setTimeout(() => {
        setCompletedToolInds((prev) => new Set(prev).add(toolInd));
        pendingOrFullCompletionsRef.current.set(toolInd, null);
      }, remainingTime);

      pendingOrFullCompletionsRef.current.set(toolInd, timeoutId);
    }
  }, []);

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

  // Check if all tools are displayed + final answer is coming
  const allToolsDisplayed = useMemo(() => {
    if (toolGroups.length === 0) return true;

    // All tools are displayed if they're all visible and completed
    const allVisible = toolGroups.every((group) => visibleTools.has(group.ind));
    const allCompleted = toolGroups.every((group) =>
      completedToolInds.has(group.ind)
    );

    return allVisible && allCompleted && isFinalAnswerComing;
  }, [toolGroups, visibleTools, completedToolInds, isFinalAnswerComing]);

  return {
    visibleTools,
    handleToolComplete,
    allToolsDisplayed,
  };
}
