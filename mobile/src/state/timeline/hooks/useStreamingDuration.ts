/* eslint-disable react-hooks/set-state-in-effect -- the 1s interval updates elapsed seconds via setState inside an effect by design. */
// useStreamingDuration.ts — tracks elapsed streaming duration.
//
// Ported from web:
//   web/src/app/app/message/messageComponents/timeline/hooks/useStreamingDuration.ts
//
// RN perf amendment: the web version drives updates with requestAnimationFrame.
// On React Native we instead use a 1s setInterval (rAF is unnecessary here since
// we only ever update once per second), while keeping the lastElapsedRef
// once-per-second guard and the shouldRunTimer gating intact. The interval is
// cleared on unmount AND whenever the timer should stop (backendDuration
// provided / not streaming / no start time) via the effect cleanup.
import { useState, useEffect, useRef } from "react";

/**
 * Hook to track elapsed streaming duration with efficient updates.
 *
 * Uses a 1s interval but only triggers re-renders when the elapsed seconds
 * value actually changes (once per second).
 *
 * @param isStreaming - Whether streaming is currently active
 * @param startTime - Timestamp when streaming started (from Date.now())
 * @param backendDuration - Duration from backend when available (freezes timer)
 * @returns Elapsed seconds since streaming started
 */
export function useStreamingDuration(
  isStreaming: boolean,
  startTime: number | undefined,
  backendDuration?: number
): number {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastElapsedRef = useRef<number>(0);

  // Determine if we should run the live timer
  // Stop the timer when backend duration is available
  const shouldRunTimer = isStreaming && backendDuration === undefined;

  useEffect(() => {
    if (!shouldRunTimer || !startTime) {
      // Don't reset when stopping - preserve last calculated value
      // Only reset when explicitly given no start time
      if (!startTime) {
        setElapsedSeconds(0);
        lastElapsedRef.current = 0;
      }
      return;
    }

    const updateElapsed = () => {
      const now = Date.now();
      const elapsed = Math.floor((now - startTime) / 1000);

      // Only update state when seconds change to avoid unnecessary re-renders
      if (elapsed !== lastElapsedRef.current) {
        lastElapsedRef.current = elapsed;
        setElapsedSeconds(elapsed);
      }
    };

    // Run once immediately so we don't wait a full second for the first tick
    updateElapsed();

    // Start the interval loop (once per second)
    intervalRef.current = setInterval(updateElapsed, 1000);

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [shouldRunTimer, startTime]);

  // Return backend duration if provided, otherwise return live elapsed time
  return backendDuration !== undefined ? backendDuration : elapsedSeconds;
}
