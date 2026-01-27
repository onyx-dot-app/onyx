import { useState, useEffect, useRef } from "react";

/**
 * Hook to track elapsed streaming duration with efficient updates.
 *
 * Uses requestAnimationFrame for accurate timing but only triggers re-renders
 * when the elapsed seconds value actually changes (once per second).
 *
 * @param isStreaming - Whether streaming is currently active
 * @param startTime - Timestamp when streaming started (from Date.now())
 * @returns Elapsed seconds since streaming started
 */
export function useStreamingDuration(
  isStreaming: boolean,
  startTime: number | undefined
): number {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const rafRef = useRef<number | null>(null);
  const lastElapsedRef = useRef<number>(0);

  useEffect(() => {
    if (!isStreaming || !startTime) {
      setElapsedSeconds(0);
      lastElapsedRef.current = 0;
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
  }, [isStreaming, startTime]);

  return elapsedSeconds;
}
