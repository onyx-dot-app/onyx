import { useState, useEffect, useRef } from "react";

/**
 * Hook to track elapsed streaming duration with efficient updates.
 *
 * Uses requestAnimationFrame for accurate timing but only triggers re-renders
 * when the elapsed seconds value actually changes (once per second).
 *
 * @param isStreaming - Whether streaming is currently active
 * @param startTime - Timestamp when streaming started (from Date.now())
 * @param backendDuration - Duration from backend when available (freezes timer)
 * @param paused - The run waits for the user (an approval); waiting is not
 *   working time, so the timer stops and resumes without counting it
 * @returns Elapsed seconds since streaming started, less paused time
 */
export function useStreamingDuration(
  isStreaming: boolean,
  startTime: number | undefined,
  backendDuration?: number,
  paused = false
): number {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const rafRef = useRef<number | null>(null);
  const lastElapsedRef = useRef<number>(0);
  const pausedMsRef = useRef(0);
  const pauseStartedRef = useRef<number | null>(null);

  // Determine if we should run the live timer
  // Stop the timer when backend duration is available
  const shouldRunTimer =
    isStreaming && backendDuration === undefined && !paused;

  // Add each finished pause to the time the timer leaves out.
  useEffect(() => {
    if (paused) {
      pauseStartedRef.current = Date.now();
    } else if (pauseStartedRef.current !== null) {
      pausedMsRef.current += Date.now() - pauseStartedRef.current;
      pauseStartedRef.current = null;
    }
  }, [paused]);

  // A new run starts with no paused time.
  useEffect(() => {
    pausedMsRef.current = 0;
  }, [startTime]);

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
      const elapsed = Math.floor(
        (now - startTime - pausedMsRef.current) / 1000
      );

      // Only update state when seconds change to avoid unnecessary re-renders
      if (elapsed !== lastElapsedRef.current) {
        lastElapsedRef.current = elapsed;
        setElapsedSeconds(elapsed);
      }

      rafRef.current = requestAnimationFrame(updateElapsed);
    };

    // Start the animation loop
    rafRef.current = requestAnimationFrame(updateElapsed);

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [shouldRunTimer, startTime]);

  // Return backend duration if provided, otherwise return live elapsed time
  return backendDuration !== undefined ? backendDuration : elapsedSeconds;
}
