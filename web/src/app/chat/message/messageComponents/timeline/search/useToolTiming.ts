import { useState, useEffect, useRef, useCallback } from "react";

const DEFAULT_ACTIVE_DURATION_MS = 1000;
const DEFAULT_COMPLETE_DURATION_MS = 1000;

export interface UseToolTimingOptions {
  /** Whether the tool has started (even if it completed instantly) */
  hasStarted: boolean;
  /** Whether the tool is complete */
  isComplete: boolean;
  /** Whether to animate transitions (affects minimum durations) */
  animate: boolean;
  /** Whether a stop packet was received */
  stopPacketSeen: boolean;
  /** Callback when the timing sequence is complete */
  onComplete: () => void;
  /** Minimum duration for the "active" state in ms (default: 1000) */
  activeDurationMs?: number;
  /** Minimum duration for the "complete" state in ms (default: 1000) */
  completeDurationMs?: number;
}

export interface UseToolTimingResult {
  /** Whether to show the "active" state (e.g., "Searching", "Reading") */
  shouldShowAsActive: boolean;
  /** Whether to show the "complete" state (e.g., "Searched", "Read") */
  shouldShowAsComplete: boolean;
}

/**
 * Generic hook that manages timing state machine for tool display.
 *
 * Ensures minimum display durations for "active" and "complete" states
 * to provide a smooth user experience even when tools complete quickly.
 *
 * State transitions:
 * - Initial -> Active (when tool starts)
 * - Active -> Complete (after min duration, when tool completes)
 * - Complete -> Done (after min duration, calls onComplete)
 *
 * When stopped/cancelled, skips intermediate states and completes immediately.
 */
export function useToolTiming({
  hasStarted,
  isComplete,
  animate,
  stopPacketSeen,
  onComplete,
  activeDurationMs = DEFAULT_ACTIVE_DURATION_MS,
  completeDurationMs = DEFAULT_COMPLETE_DURATION_MS,
}: UseToolTimingOptions): UseToolTimingResult {
  const [startTime, setStartTime] = useState<number | null>(null);
  const [shouldShowAsActive, setShouldShowAsActive] = useState(false);
  const [shouldShowAsComplete, setShouldShowAsComplete] = useState(false);

  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const completeTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const completionHandledRef = useRef(false);

  const clearAllTimeouts = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (completeTimeoutRef.current) {
      clearTimeout(completeTimeoutRef.current);
      completeTimeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (hasStarted && startTime === null) {
      setStartTime(Date.now());
      setShouldShowAsActive(true);
    }
  }, [hasStarted, startTime]);

  useEffect(() => {
    if (isComplete && startTime !== null && !completionHandledRef.current) {
      completionHandledRef.current = true;

      if (stopPacketSeen) {
        clearAllTimeouts();
        setShouldShowAsActive(false);
        setShouldShowAsComplete(false);
        onComplete();
        return;
      }

      const elapsedTime = Date.now() - startTime;
      const minimumActiveDuration = animate ? activeDurationMs : 0;
      const minimumCompleteDuration = animate ? completeDurationMs : 0;

      const handleActiveToComplete = () => {
        setShouldShowAsActive(false);
        setShouldShowAsComplete(true);

        completeTimeoutRef.current = setTimeout(() => {
          setShouldShowAsComplete(false);
          onComplete();
        }, minimumCompleteDuration);
      };

      if (elapsedTime >= minimumActiveDuration) {
        handleActiveToComplete();
      } else {
        const remainingTime = minimumActiveDuration - elapsedTime;
        timeoutRef.current = setTimeout(handleActiveToComplete, remainingTime);
      }
    }
  }, [
    isComplete,
    startTime,
    animate,
    stopPacketSeen,
    onComplete,
    clearAllTimeouts,
    activeDurationMs,
    completeDurationMs,
  ]);

  useEffect(() => {
    if (stopPacketSeen) {
      clearAllTimeouts();
      setShouldShowAsActive(false);
      setShouldShowAsComplete(false);
    }
  }, [stopPacketSeen, clearAllTimeouts]);

  useEffect(() => {
    return () => {
      clearAllTimeouts();
    };
  }, [clearAllTimeouts]);

  return {
    shouldShowAsActive,
    shouldShowAsComplete,
  };
}
