import { useState, useEffect, useRef } from "react";

/** Time a run spent waiting for approvals; the timer leaves it out. */
export interface ApprovalWait {
  /** Total length of the finished waits. */
  excludedMs: number;
  /** When the current wait started, or null while the run works. */
  since: number | null;
}

/**
 * Hook to track elapsed streaming duration with efficient updates.
 *
 * Uses requestAnimationFrame for accurate timing but only triggers re-renders
 * when the elapsed seconds value actually changes (once per second).
 *
 * @param isStreaming - Whether streaming is currently active
 * @param startTime - Timestamp when streaming started (from Date.now())
 * @param backendDuration - Duration from backend when available (freezes timer)
 * @param approvalWait - Waiting is not working time, so the timer stops
 *   during a wait and leaves out the finished ones
 * @returns Elapsed seconds since streaming started, less the waits
 */
export function useStreamingDuration(
  isStreaming: boolean,
  startTime: number | undefined,
  backendDuration?: number,
  approvalWait?: ApprovalWait
): number {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const rafRef = useRef<number | null>(null);
  const lastElapsedRef = useRef<number>(0);
  const excludedMs = approvalWait?.excludedMs ?? 0;
  const waitingSince = approvalWait?.since ?? null;

  // Determine if we should run the live timer
  // Stop the timer when backend duration is available
  const shouldRunTimer =
    isStreaming && backendDuration === undefined && waitingSince === null;

  useEffect(() => {
    if (!startTime) {
      // Only reset when explicitly given no start time
      setElapsedSeconds(0);
      lastElapsedRef.current = 0;
      return;
    }

    const updateElapsed = (now: number) => {
      const elapsed = Math.floor((now - startTime - excludedMs) / 1000);
      // Only update state when seconds change to avoid unnecessary re-renders
      if (elapsed !== lastElapsedRef.current) {
        lastElapsedRef.current = elapsed;
        setElapsedSeconds(elapsed);
      }
    };

    if (!shouldRunTimer) {
      // A wait holds the time at its start, also for a header that mounts
      // during it. Otherwise stopping keeps the last value.
      if (waitingSince !== null) updateElapsed(waitingSince);
      return;
    }

    const tick = () => {
      updateElapsed(Date.now());
      rafRef.current = requestAnimationFrame(tick);
    };

    // Start the animation loop
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [shouldRunTimer, startTime, excludedMs, waitingSince]);

  // Return backend duration if provided, otherwise return live elapsed time
  return backendDuration !== undefined ? backendDuration : elapsedSeconds;
}
