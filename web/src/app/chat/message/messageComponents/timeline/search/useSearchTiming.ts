import { useState, useEffect, useRef, useCallback } from "react";
import {
  SEARCHING_MIN_DURATION_MS,
  SEARCHED_MIN_DURATION_MS,
} from "./searchStateUtils";

export interface UseSearchTimingOptions {
  /** Whether the search has started (even if it completed instantly) */
  hasStarted: boolean;
  /** Whether the search is complete */
  isComplete: boolean;
  /** Whether to animate transitions (affects minimum durations) */
  animate: boolean;
  /** Whether a stop packet was received */
  stopPacketSeen: boolean;
  /** Callback when the timing sequence is complete */
  onComplete: () => void;
}

export interface UseSearchTimingResult {
  /** Whether to show the "Searching" state */
  shouldShowAsSearching: boolean;
  /** Whether to show the "Searched" state */
  shouldShowAsSearched: boolean;
}

/**
 * Hook that manages the timing state machine for search display.
 *
 * Ensures minimum display durations for "Searching" and "Searched" states
 * to provide a smooth user experience even when searches complete quickly.
 *
 * State transitions:
 * - Initial -> Searching (when search starts)
 * - Searching -> Searched (after min duration, when search completes)
 * - Searched -> Complete (after min duration, calls onComplete)
 *
 * When stopped/cancelled, skips intermediate states and completes immediately.
 */
export function useSearchTiming({
  hasStarted,
  isComplete,
  animate,
  stopPacketSeen,
  onComplete,
}: UseSearchTimingOptions): UseSearchTimingResult {
  const [searchStartTime, setSearchStartTime] = useState<number | null>(null);
  const [shouldShowAsSearching, setShouldShowAsSearching] = useState(false);
  const [shouldShowAsSearched, setShouldShowAsSearched] = useState(false);

  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const searchedTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const completionHandledRef = useRef(false);

  // Cleanup helper
  const clearAllTimeouts = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (searchedTimeoutRef.current) {
      clearTimeout(searchedTimeoutRef.current);
      searchedTimeoutRef.current = null;
    }
  }, []);

  // Track when search starts
  useEffect(() => {
    if (hasStarted && searchStartTime === null) {
      setSearchStartTime(Date.now());
      setShouldShowAsSearching(true);
    }
  }, [hasStarted, searchStartTime]);

  // Handle search completion with minimum duration
  useEffect(() => {
    if (
      isComplete &&
      searchStartTime !== null &&
      !completionHandledRef.current
    ) {
      completionHandledRef.current = true;

      // If stopped, skip intermediate states and complete immediately
      if (stopPacketSeen) {
        clearAllTimeouts();
        setShouldShowAsSearching(false);
        setShouldShowAsSearched(false);
        onComplete();
        return;
      }

      const elapsedTime = Date.now() - searchStartTime;
      const minimumSearchingDuration = animate ? SEARCHING_MIN_DURATION_MS : 0;
      const minimumSearchedDuration = animate ? SEARCHED_MIN_DURATION_MS : 0;

      const handleSearchingToSearched = () => {
        setShouldShowAsSearching(false);
        setShouldShowAsSearched(true);

        searchedTimeoutRef.current = setTimeout(() => {
          setShouldShowAsSearched(false);
          onComplete();
        }, minimumSearchedDuration);
      };

      if (elapsedTime >= minimumSearchingDuration) {
        // Enough time has passed, transition immediately
        handleSearchingToSearched();
      } else {
        // Delay the transition
        const remainingTime = minimumSearchingDuration - elapsedTime;
        timeoutRef.current = setTimeout(
          handleSearchingToSearched,
          remainingTime
        );
      }
    }
  }, [
    isComplete,
    searchStartTime,
    animate,
    stopPacketSeen,
    onComplete,
    clearAllTimeouts,
  ]);

  // Cleanup timeouts when stopped
  useEffect(() => {
    if (stopPacketSeen) {
      clearAllTimeouts();
      setShouldShowAsSearching(false);
      setShouldShowAsSearched(false);
    }
  }, [stopPacketSeen, clearAllTimeouts]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      clearAllTimeouts();
    };
  }, [clearAllTimeouts]);

  return {
    shouldShowAsSearching,
    shouldShowAsSearched,
  };
}
